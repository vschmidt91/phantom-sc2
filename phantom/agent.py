import lzma
import math
import pickle
import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import chain
from typing import TYPE_CHECKING

import numpy as np
from ares.behaviors.macro.mining import TOWNHALL_RADIUS
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

from phantom.common.action import Action, Attack, Move, MovePath, UseAbility
from phantom.common.blocked_positions import BlockedPositionTracker
from phantom.common.config import BotConfig
from phantom.common.constants import (
    CHANGELINGS,
    CIVILIANS,
    ENEMY_CIVILIANS,
    GAS_BY_RACE,
)
from phantom.common.cost import Cost
from phantom.common.parameter_sampler import ParameterSampler, Prior
from phantom.common.utils import to_point
from phantom.macro.build_order import BUILD_ORDERS
from phantom.macro.builder import Builder, BuilderParameters, MacroPlan
from phantom.macro.mining import MiningContext, MiningState
from phantom.macro.strategy import Strategy, StrategyParameters
from phantom.micro.combat import CombatParameters, CombatState, CombatStep
from phantom.micro.corrosive_bile import CorrosiveBile
from phantom.micro.creep import CreepSpread, CreepTumors
from phantom.micro.dodge import Dodge
from phantom.micro.overseers import Overseers
from phantom.micro.queens import Queens
from phantom.micro.simulator import CombatSimulator, CombatSimulatorParameters

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
class AgentParameters:
    def __init__(self, sampler: ParameterSampler) -> None:
        self.gas_ratio_learning_rate_log = sampler.add(Prior(-7, 1, max=0))

    @property
    def gas_ratio_learning_rate(self) -> float:
        return np.exp(self.gas_ratio_learning_rate_log.value)


class Agent:
    def __init__(self, bot: "PhantomBot", config: BotConfig) -> None:
        self.bot = bot
        self.config = config
        self.sampler = ParameterSampler()
        self.build_order = BUILD_ORDERS[self.config.build_order]
        self.simulator = CombatSimulator(bot, CombatSimulatorParameters(self.sampler))
        self.combat = CombatState(bot, CombatParameters(self.sampler), self.simulator)
        self.builder = Builder(bot, BuilderParameters(self.sampler))
        self.creep_tumors = CreepTumors(bot)
        self.creep_spread = CreepSpread(bot)
        self.corrosive_biles = CorrosiveBile(bot)
        self.dodge = Dodge(bot)
        self.overseers = Overseers(bot)
        self.blocked_positions = BlockedPositionTracker(bot)
        self.queens = Queens(bot)
        self.strategy_paramaters = StrategyParameters(self.sampler)
        self.harvesters = MiningState(bot)
        self.build_order_completed = False
        self.gas_ratio = 0.0
        self.parameters = AgentParameters(self.sampler)
        self._load_parameters()
        self._log_parameters()

    def on_step(self) -> Mapping[Unit, Action]:
        if self.config.debug_draw:
            self.builder.debug_draw_plans()

        enemy_combatants = self.bot.enemy_units.exclude_type(ENEMY_CIVILIANS)
        combatants = self.bot.units.exclude_type(
            {
                *CIVILIANS,
                UnitTypeId.QUEEN,
                UnitTypeId.QUEENBURROWED,
            }
        )
        queens = self.bot.units(
            {
                UnitTypeId.QUEEN,
                UnitTypeId.QUEENBURROWED,
            }
        )
        overseers = self.bot.units(
            {
                UnitTypeId.OVERSEER,
                UnitTypeId.OVERSEERSIEGEMODE,
            }
        )
        harvester_return_targets = self.bot.townhalls.ready
        strategy = Strategy(self.bot, self.strategy_paramaters)

        actions = dict[Unit, Action]()
        macro_plans = list[MacroPlan]()
        if not self.build_order_completed:
            if not self.bot.mediator.is_position_safe(
                grid=self.bot.ground_grid,
                position=self.bot.mediator.get_own_nat,
                weight_safety_limit=10.0,
            ):
                self.build_order_completed = True
            if self.bot.mediator.get_did_enemy_rush:
                self.build_order_completed = True
            if step := self.build_order.execute(self.bot):
                actions.update(step.actions)
                macro_plans.extend(step.plans)
            else:
                logger.info("Build order completed.")
                self.build_order_completed = True
        else:
            macro_plans.extend(
                chain(
                    self.builder.make_composition(strategy.composition_target),
                    self.builder.make_upgrades(strategy.composition_target, strategy.filter_upgrade),
                    strategy.morph_overlord(),
                    self.builder.expand(),
                    strategy.make_spines(),
                    strategy.make_spores(),
                )
            )

        combat = self.combat.on_step()
        self.creep_tumors.on_step()
        self.creep_spread.on_step()
        self.dodge.on_step()
        self.blocked_positions.on_step()

        def should_harvest_resource(r: Unit) -> bool:
            p = to_point(r.position)
            return self.bot.mediator.is_position_safe(
                grid=self.bot.ground_grid,
                position=self.bot.gather_targets[p],
                weight_safety_limit=6.0,
            )

        required = Cost()
        required += self.builder.get_planned_cost()
        required += self.bot.cost.of_composition(strategy.composition_deficit)
        required -= self.bot.bank
        required = Cost.max(required, Cost())

        if required.minerals == 0 and required.vespene == 0:
            gas_ratio = 0.5
        else:
            gas_ratio = required.vespene / (required.minerals + required.vespene)
        self.gas_ratio += self.parameters.gas_ratio_learning_rate * np.sign(gas_ratio - self.gas_ratio)
        self.gas_ratio = max(0, min(1, self.gas_ratio))

        harvesters = list[Unit]()
        harvesters_exclude = self.builder.assigned_tags | self.bot.pending.keys()
        harvesters.extend(self.bot.workers.tags_not_in(harvesters_exclude))
        harvesters.extend(self.bot.workers_off_map.values())

        gas_target = math.ceil(len(harvesters) * self.gas_ratio)
        if not self.bot.researched_speed and self.bot.harvestable_gas_buildings:
            gas_target = 3
        else:
            macro_plans.extend(self._build_gas(gas_target))

        for plan in macro_plans:
            self.builder.add(plan)
        self.builder.on_step()

        mineral_fields = [m for m in self.bot.all_taken_minerals if should_harvest_resource(m)]
        gas_buildings = [g for g in self.bot.harvestable_gas_buildings if should_harvest_resource(g)]

        resoure_observation = MiningContext(
            self.bot,
            harvesters,
            mineral_fields,
            gas_buildings,
            gas_target,
        )
        resources = self.harvesters.step(resoure_observation)

        for harvester in harvesters:
            if not combat.is_unit_safe(
                harvester, weight_safety_limit=6.0
            ) or self.bot.damage_tracker.time_since_last_damage(harvester) < min(self.bot.state.game_loop, 50):
                actions[harvester] = combat.retreat_with(harvester)
            elif action := resources.gather_with(harvester, harvester_return_targets):
                actions[harvester] = action

        for changeling in self.bot.units(CHANGELINGS):
            if action := self._search_with(changeling):
                actions[changeling] = action

        combatant_actions = dict[Unit, Action]()
        for combatant in combatants:
            if (
                (combatant.type_id == UnitTypeId.RAVAGER and (action := self.corrosive_biles.bile_with(combatant)))
                or (combatant.type_id == UnitTypeId.ROACH and (action := self._burrow(combatant)))
                or (combatant.type_id == UnitTypeId.ROACHBURROWED and (action := self._unburrow(combatant, combat)))
                or (action := combat.fight_with(combatant))
                or (action := self._search_with(combatant))
            ):
                combatant_actions[combatant] = action

        if self.config.max_actions < len(combatant_actions):
            self.bot.add_replay_tag("action_throttling")
            logger.debug(f"Limiting actions from {len(combatant_actions)} to {self.config.max_actions}")
            selected_keys = list(combatant_actions.keys())
            random.shuffle(selected_keys)
            selected_keys = selected_keys[: self.config.max_actions]
            combatant_actions = {k: combatant_actions[k] for k in selected_keys}
        actions.update(combatant_actions)

        if self.bot.actual_iteration > 1 or not self.config.skip_first_iteration:
            actions.update(self.builder.get_actions())

        for changeling in self.bot.units(CHANGELINGS):
            if action := self._search_with(changeling):
                actions[changeling] = action

        for structure in self.bot.structures.not_ready:
            if structure.health_percentage < 0.05:
                actions[structure] = UseAbility(AbilityId.CANCEL)

        actions.update(self._micro_queens(queens, combat))

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
            if action := combat.keep_unit_safe(overlord):
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
            self.sampler.tell(fitness)
            with lzma.open(self.config.params_path, "wb") as f:
                pickle.dump(self.sampler, f)

    def _micro_queens(self, queens: Sequence[Unit], combat: CombatStep) -> Mapping[Unit, Action]:
        should_inject = self.bot.supply_used + self.bot.bank.larva < 200
        tumor_count = (
            self.creep_tumors.unspread_tumor_count
            + self.bot.count_pending(UnitTypeId.CREEPTUMOR)
            + self.bot.count_pending(UnitTypeId.CREEPTUMORQUEEN)
        )
        tumor_limit = min(3.0 * len(queens), self.bot.time / 30.0)
        should_spread_creep = tumor_count < tumor_limit and self.bot.mediator.get_creep_coverage < 90
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
            grid=self.bot.clean_ground_grid,
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
                self.sampler.strategy = parameters.strategy
                self.sampler.population = parameters.population
                self.sampler.loss_values = parameters.loss_values
        except Exception as error:
            logger.warning(f"{error=} while loading {self.config.params_path}")

        if self.config.training:
            logger.info("Sampling bot parameters")
            self.sampler.ask()
        else:
            self.sampler.ask_best()

    def _build_gas(self, gas_harvester_target: int) -> Iterable[MacroPlan]:
        gas_type = GAS_BY_RACE[self.bot.race]
        gas_have = (
            len(self.bot.harvestable_gas_buildings)
            + self.bot.count_pending(gas_type)
            + self.bot.count_planned(gas_type)
        )
        gas_max = len(self.bot.all_taken_geysers)
        gas_want = min(gas_max, math.ceil(gas_harvester_target / self.bot.harvesters_per_gas_building))
        for _ in range(gas_have, gas_want):
            yield MacroPlan(gas_type)

    def _search_with(self, unit: Unit) -> Action | None:
        if not (unit.is_idle or unit.is_gathering or unit.is_returning):
            return None
        elif self.bot.time < 8 * 60 and self.bot.enemy_start_locations:
            return Move(Point2(random.choice(self.bot.enemy_start_locations)))
        elif self.bot.all_enemy_units:
            target = cy_closest_to(unit.position, self.bot.all_enemy_units)
            return Attack(target.position)
        target = self.bot.random_point(near=unit.position)
        if self.bot.is_visible(target):
            return None
        if self.bot.clean_ground_grid[to_point(target)] == np.inf and not unit.is_flying:
            return None
        return Move(target)

    def _burrow(self, unit: Unit) -> Action | None:
        if (
            UpgradeId.BURROW in self.bot.state.upgrades
            and unit.health_percentage < 0.3
            and not unit.is_revealed
            and unit.weapon_cooldown
            and not self.bot.mediator.get_is_detected(unit=unit, by_enemy=True)
        ):
            return UseAbility(AbilityId.BURROWDOWN)
        else:
            return None

    def _unburrow(self, unit: Unit, combat: CombatStep) -> Action | None:
        if unit.health_percentage > 0.9:
            return UseAbility(AbilityId.BURROWUP)
        elif UpgradeId.TUNNELINGCLAWS in self.bot.state.upgrades and (action := combat.keep_unit_safe(unit)):
            return action
        else:
            return None

    def _log_parameters(self) -> None:
        logger.info(f"{self.parameters.__dict__=}")
        logger.info(f"{self.simulator.parameters.__dict__=}")
        logger.info(f"{self.combat.parameters.__dict__=}")
        logger.info(f"{self.builder.parameters.__dict__=}")
        logger.info(f"{self.strategy_paramaters.__dict__=}")
