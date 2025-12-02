import lzma
import math
import pickle
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import chain
from typing import TYPE_CHECKING

import numpy as np
from ares.behaviors.macro.mining import TOWNHALL_RADIUS
from ares.consts import UnitRole
from cython_extensions import cy_closest_to, cy_distance_to
from loguru import logger
from s2clientprotocol.score_pb2 import CategoryScoreDetails
from sc2.data import Race, Result
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.score import ScoreDetails
from sc2.unit import Unit

from phantom.blocked_positions import BlockedPositionTracker
from phantom.common.action import Action, Attack, HoldPosition, Move, MovePath, UseAbility
from phantom.common.constants import (
    CHANGELINGS,
    CIVILIANS,
    ENEMY_CIVILIANS,
    GAS_BY_RACE,
)
from phantom.common.cost import Cost
from phantom.common.utils import to_point
from phantom.config import BotConfig
from phantom.macro.build_order import BUILD_ORDERS
from phantom.macro.main import Macro, MacroParameters, MacroPlan
from phantom.macro.strategy import Strategy, StrategyParameters
from phantom.micro.corrosive_bile import CorrosiveBile
from phantom.micro.creep import CreepSpread, CreepTumors
from phantom.micro.dodge import DodgeState
from phantom.micro.main import CombatParameters, CombatState, CombatStep
from phantom.micro.overseers import Overseers
from phantom.micro.queens import Queens
from phantom.micro.transfuse import Transfuse
from phantom.parameter_sampler import ParameterSampler, Prior
from phantom.resources.main import ResourceState
from phantom.resources.observation import ResourceObservation

if TYPE_CHECKING:
    from phantom.main import PhantomBot


def score_to_fitness(score: ScoreDetails, vespene_weight: float = 2.0) -> float:
    def sum_category(category: CategoryScoreDetails) -> float:
        return sum(
            (
                category.army,
                category.economy,
                category.none,
                category.technology,
                category.upgrade,
            )
        )

    lost_minerals = sum(
        (
            sum_category(score._proto.lost_minerals),
            sum_category(score._proto.friendly_fire_minerals),
        )
    )
    lost_vespene = sum(
        (
            sum_category(score._proto.lost_vespene),
            sum_category(score._proto.friendly_fire_vespene),
        )
    )
    lost_total = lost_minerals + lost_vespene * vespene_weight

    killed_minerals = sum_category(score._proto.killed_minerals)
    killed_vespene = sum_category(score._proto.killed_vespene)
    killed_total = killed_minerals + killed_vespene * vespene_weight

    return killed_total / max(1.0, lost_total + killed_total)


@dataclass
class Agent:
    def __init__(self, bot: "PhantomBot", config: BotConfig) -> None:
        self.bot = bot
        self.config = config
        self.parameters = ParameterSampler()
        self.build_order = BUILD_ORDERS[self.config.build_order]
        self.combat = CombatState(bot, CombatParameters(self.parameters))
        self.macro = Macro(bot, MacroParameters(self.parameters))
        self.creep_tumors = CreepTumors(bot)
        self.creep_spread = CreepSpread(bot)
        self.corrosive_biles = CorrosiveBile(bot)
        self.dodge = DodgeState(bot)
        self.overseers = Overseers(bot)
        self.blocked_positions = BlockedPositionTracker(bot)
        self.queens = Queens(bot)
        self.strategy_paramaters = StrategyParameters(self.parameters)
        self.resources = ResourceState(bot)
        self.transfuse = Transfuse(bot)
        self.build_order_completed = False
        self.gas_ratio = 0.0
        self.gas_ratio_learning_rate_log = self.parameters.add(Prior(-7, 1, max=0))
        self._load_parameters()

    @property
    def gas_ratio_learning_rate(self) -> float:
        return np.exp(self.gas_ratio_learning_rate_log.value)

    def on_step(self) -> Mapping[Unit, Action]:
        if self.config.debug_draw:
            self.macro.debug_draw_plans()

        enemy_combatants = self.bot.enemy_units.exclude_type(ENEMY_CIVILIANS)
        combatants = self.bot.units.exclude_type(
            {
                *CIVILIANS,
                UnitTypeId.QUEEN,
                UnitTypeId.QUEENBURROWED,
            }
        )
        strategy = Strategy(self.bot, self.strategy_paramaters)

        if self.bot.mediator.get_did_enemy_rush:
            self.build_order_completed = True

        build_order_actions = dict[Unit, Action]()
        if not self.build_order_completed:
            if not self.bot.mediator.is_position_safe(
                grid=self.bot.mediator.get_ground_grid,
                position=self.bot.mediator.get_own_nat,
                weight_safety_limit=10.0,
            ):
                self.build_order_completed = True
            if step := self.build_order.execute(self.bot):
                build_order_actions.update(step.actions)
                for plan in step.plans:
                    self.macro.add(plan)
            else:
                logger.info("Build order completed.")
                self.build_order_completed = True
        else:
            for plan in chain(
                self.macro.make_composition(strategy.composition_target),
                self.macro.make_upgrades(strategy.composition_target, strategy.filter_upgrade),
                strategy.morph_overlord(),
                self.macro.expand(),
                strategy.make_spines(),
                strategy.make_spores(),
            ):
                self.macro.add(plan)

        combat = self.combat.on_step()
        self.corrosive_biles.on_step()
        self.creep_tumors.on_step()
        self.creep_spread.on_step()
        self.dodge.on_step()
        self.transfuse.on_step()
        self.blocked_positions.on_step()
        self.macro.on_step()

        def should_harvest_resource(r: Unit) -> bool:
            p = to_point(r.position)
            check_points = [
                to_point(self.bot.gather_targets[p]),
                to_point(self.bot.return_targets[p]),
            ]
            return all(self.bot.mediator.get_ground_grid[p] < 6.0 for p in check_points)

        required = Cost()
        required += self.macro.get_planned_cost()
        required += self.bot.cost.of_composition(strategy.composition_deficit)
        required -= self.bot.bank

        if required.minerals <= 0 and required.vespene <= 0:
            gas_ratio = 5 / 9
        else:
            mineral_trips = max(0.0, required.minerals / 5)
            vespene_trips = max(0.0, required.vespene / 4)
            gas_ratio = vespene_trips / (mineral_trips + vespene_trips)
        self.gas_ratio += self.gas_ratio_learning_rate * np.sign(gas_ratio - self.gas_ratio)
        self.gas_ratio = max(0, min(1, self.gas_ratio))

        harvesters = list[Unit]()
        harvesters.extend(self.bot.mediator.get_units_from_role(role=UnitRole.GATHERING))
        harvesters.extend(self.bot.workers_off_map.values())

        gas_target = math.ceil(len(harvesters) * self.gas_ratio)
        if not self.bot.researched_speed and self.bot.harvestable_gas_buildings:
            gas_target = 3

        mineral_fields = [m for m in self.bot.all_taken_minerals if should_harvest_resource(m)]
        gas_buildings = [g for g in self.bot.harvestable_gas_buildings if should_harvest_resource(g)]

        resoure_observation = ResourceObservation(
            self.bot,
            harvesters,
            mineral_fields,
            gas_buildings,
            gas_target,
        )
        resources = self.resources.step(resoure_observation)
        harvester_return_targets = self.bot.townhalls.ready

        gas_type = GAS_BY_RACE[self.bot.race]
        gas_have = (
            len(self.bot.harvestable_gas_buildings)
            + self.bot.count_pending(gas_type)
            + self.bot.count_planned(gas_type)
        )
        gas_max = len(self.bot.all_taken_geysers)
        gas_want = min(gas_max, math.ceil(resoure_observation.gas_target / self.bot.harvesters_per_gas_building))
        if gas_have < gas_want:
            self.macro.add(MacroPlan(gas_type))

        def micro_harvester(u: Unit) -> Action | None:
            if (
                6.0 < self.bot.mediator.get_ground_grid[to_point(u.position)] < np.inf
            ) and combat.context.enemy_combatants:
                closest_enemy = cy_closest_to(u.position, combat.context.enemy_combatants)
                if (
                    local_outcome := combat.context.prediction.outcome_local.get(closest_enemy.tag) is not None
                ) and local_outcome > 0:
                    return combat.retreat_with(u)
            return resources.gather_with(u, harvester_return_targets)

        def keep_unit_safe(unit: Unit) -> Action | None:
            if not combat.is_unit_safe(unit):
                return combat.retreat_with(unit)
            return None

        def do_unburrow(u: Unit) -> Action | None:
            if u.health_percentage > 0.9:
                return UseAbility(AbilityId.BURROWUP)
            elif UpgradeId.TUNNELINGCLAWS not in self.bot.state.upgrades:
                return None
            elif self.bot.mediator.get_ground_grid[to_point(u.position)] > 1:
                return combat.retreat_with(u)
            return HoldPosition()

        def do_burrow(u: Unit) -> Action | None:
            if (
                UpgradeId.BURROW not in self.bot.state.upgrades
                or u.health_percentage > 0.3
                or u.is_revealed
                or not u.weapon_cooldown
                or self.bot.mediator.get_is_detected(unit=u, by_enemy=True)
            ):
                return None
            return UseAbility(AbilityId.BURROWDOWN)

        micro_handlers = {
            UnitTypeId.RAVAGER: self.corrosive_biles.bile_with,
            UnitTypeId.ROACH: do_burrow,
            UnitTypeId.ROACHBURROWED: do_unburrow,
        }

        def micro_unit(u: Unit) -> Action | None:
            if (handler := micro_handlers.get(u.type_id)) and (action := handler(u)):
                return action
            return combat.fight_with(u) or search_with(u)

        def search_with(unit: Unit) -> Action | None:
            if not (unit.is_idle or unit.is_gathering or unit.is_returning):
                return None
            elif self.bot.time < 8 * 60 and self.bot.enemy_start_locations:
                return Move(Point2(random.choice(self.bot.enemy_start_locations)))
            # elif self.bot.enemy_units:
            #     target = cy_closest_to(unit.position, self.bot.enemy_units)
            #     return Attack(target.position)
            elif self.bot.all_enemy_units:
                target = cy_closest_to(unit.position, self.bot.all_enemy_units)
                return Attack(target.position)
            target = self.bot.random_point(near=unit.position)
            if self.bot.is_visible(target):
                return None
            if self.bot.mediator.get_cached_ground_grid[to_point(target)] == np.inf and not unit.is_flying:
                return None
            return Move(target)

        actions = {
            **build_order_actions,
            **{u: a for u in harvesters if (a := micro_harvester(u))},
            **{u: a for u in self.bot.units(CHANGELINGS) if (a := search_with(u))},
            **{u: a for u in combatants if (a := micro_unit(u))},
        }

        actions.update(self.macro.get_actions())

        for changeling in self.bot.units(CHANGELINGS):
            if action := search_with(changeling):
                actions[changeling] = action

        for structure in self.bot.structures.not_ready:
            if structure.health_percentage < 0.05:
                actions[structure] = UseAbility(AbilityId.CANCEL)

        queens = self.bot.units(
            {
                UnitTypeId.QUEEN,
                UnitTypeId.QUEENBURROWED,
            }
        )
        actions.update(self._micro_queens(queens, combat))

        overseers = self.bot.units(
            {
                UnitTypeId.OVERSEER,
                UnitTypeId.OVERSEERSIEGEMODE,
            }
        )
        detection_targets = list(map(Point2, self.blocked_positions.blocked_positions))
        actions.update(
            self.overseers.get_actions(
                overseers=overseers,
                scout_targets=enemy_combatants or self.bot.all_enemy_units,
                detection_targets=detection_targets,
                combat=combat,
            )
        )

        for overlord in self.bot.units(UnitTypeId.OVERLORD):
            if self.bot.actual_iteration == 1:
                actions[overlord] = self._send_overlord_scout(overlord)
            if action := keep_unit_safe(overlord):
                actions[overlord] = action

        for tumor in self.creep_tumors.active_tumors:
            if action := self.creep_spread.spread_with(tumor):
                actions[tumor] = action

        for unit in self.bot.units:
            if action := self.dodge.dodge_with(unit):
                actions[unit] = action

        return actions

    def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId) -> None:
        if unit.type_id == UnitTypeId.CREEPTUMORBURROWED:
            self.creep_tumors.on_tumor_completed(unit, previous_type == UnitTypeId.CREEPTUMORQUEEN)

    def on_end(self, game_result: Result):
        if self.config.training:
            fitness = score_to_fitness(self.bot.state.score)
            logger.info(f"Training parameters with {fitness=}")
            self.parameters.tell(fitness)
            with lzma.open(self.config.params_path, "wb") as f:
                pickle.dump(self.parameters, f)

    def _micro_queens(self, queens: Sequence[Unit], combat: CombatStep) -> Mapping[Unit, Action]:
        should_inject = self.bot.supply_used + self.bot.bank.larva < 200
        tumor_count = (
            self.creep_tumors.unspread_tumor_count
            + self.bot.count_pending(UnitTypeId.CREEPTUMOR)
            + self.bot.count_pending(UnitTypeId.CREEPTUMORQUEEN)
        )
        tumor_limit = min(3.0 * len(queens), self.bot.time / 30.0)
        should_spread_creep = tumor_count < tumor_limit
        return self.queens.get_actions(
            queens=queens,
            inject_targets=self.bot.townhalls.ready if should_inject else [],
            creep=self.creep_spread if should_spread_creep else None,
            combat=combat,
        )

    def _send_overlord_scout(self, overlord: Unit) -> Action:
        scout_path = list[Point2]()
        sight_range = overlord.sight_range
        townhall_size = self.bot.townhalls[0].radius - 1.0
        worker_speed = 1.4 * self.bot.workers[0].real_speed
        overlord_speed = 1.4 * overlord.real_speed
        sensitivity = int(sight_range)
        rush_path = self.bot.mediator.find_raw_path(
            start=self.bot.start_location,
            target=self.bot.enemy_start_locations[0],
            grid=self.bot.mediator.get_cached_ground_grid,
            sensitivity=sensitivity,
        )
        for p in rush_path:
            overlord_duration = (cy_distance_to(overlord.position, p) - sight_range) / overlord_speed
            worker_duration = cy_distance_to(self.bot.enemy_start_locations[0], p) / worker_speed
            if overlord_duration < worker_duration:
                continue
            if cy_distance_to(p, self.bot.mediator.get_enemy_nat) < sight_range + townhall_size:
                break
            if cy_distance_to(p, self.bot.mediator.get_enemy_ramp.barracks_correct_placement) < sight_range:
                break
            scout_path.append(p)
        nat_scout_point = self.bot.mediator.get_enemy_nat.towards(scout_path[-1], TOWNHALL_RADIUS + sight_range)
        scout_path.append(nat_scout_point)
        if self.bot.enemy_race in {Race.Zerg, Race.Random}:
            safe_spot = rush_path[len(rush_path) // 2]
        else:
            safe_spot = self.bot.mediator.get_ol_spot_near_enemy_nat
        scout_path.append(safe_spot)
        return MovePath(scout_path)

    def _load_parameters(self) -> None:
        try:
            with lzma.open(self.config.params_path, "rb") as f:
                parameters: ParameterSampler = pickle.load(f)
                self.parameters.strategy = parameters.strategy
                self.parameters.population = parameters.population
                self.parameters.loss_values = parameters.loss_values
        except Exception as error:
            logger.warning(f"{error=} while loading {self.config.params_path}")

        if self.config.training:
            logger.info("Sampling bot parameters")
            self.parameters.ask()
        else:
            self.parameters.ask_best()
        logger.info(f"{self.parameters.parameters=}")
