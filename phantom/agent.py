import lzma
import math
import pickle
import random
from collections.abc import Mapping
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
from sc2.units import Units

from phantom.combat.corrosive_bile import CorrosiveBile
from phantom.combat.dodge import DodgeState
from phantom.combat.main import CombatParameters, CombatState
from phantom.combat.transfuse import Transfuse
from phantom.common.action import Action, Attack, HoldPosition, Move, MovePath, UseAbility
from phantom.common.constants import (
    CHANGELINGS,
    CIVILIANS,
    ENEMY_CIVILIANS,
    ENERGY_COST,
    ENERGY_GENERATION_RATE,
    GAS_BY_RACE,
)
from phantom.common.cost import Cost
from phantom.common.distribute import distribute
from phantom.common.utils import pairwise_distances, to_point
from phantom.config import BotConfig
from phantom.creep import CreepSpread, CreepTumors
from phantom.macro.build_order import BUILD_ORDERS
from phantom.macro.main import Macro, MacroParameters, MacroPlan
from phantom.macro.strategy import Strategy, StrategyParameters
from phantom.parameter_sampler import ParameterSampler, Prior
from phantom.resources.main import ResourceState
from phantom.resources.observation import ResourceObservation
from phantom.scout import ScoutState

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
        self.scout = ScoutState(bot)
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
        combatants = self.bot.units.exclude_type(CIVILIANS)
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

        injecters = self.bot.units(UnitTypeId.QUEEN)
        inject_targets = self.bot.townhalls.ready
        inject_assignment = distribute(
            injecters,
            inject_targets,
            pairwise_distances(
                [a.position for a in injecters],
                [b.position for b in inject_targets],
            ),
        )

        macro_actions = self.macro.on_step()

        should_inject = self.bot.supply_used + self.bot.bank.larva < 200
        tumor_count = (
            self.creep_tumors.unspread_tumor_count
            + self.bot.count_pending(UnitTypeId.CREEPTUMOR)
            + self.bot.count_pending(UnitTypeId.CREEPTUMORQUEEN)
        )
        tumor_limit = min(3.0 * self.bot.count_actual(UnitTypeId.QUEEN), self.bot.time / 30.0)
        should_spread_creep = tumor_count < tumor_limit

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
        # if not self.bot.count(UnitTypeId.LAIR, include_planned=False):
        #     gas_want = min(1, gas_want)
        if gas_have < gas_want:
            self.macro.add(MacroPlan(gas_type))

        def inject_with_queen(q: Unit) -> Action | None:
            if not should_inject:
                return None
            if target := inject_assignment.get(q):
                distance = cy_distance_to(q.position, target.position) - q.radius - target.radius
                time_to_reach_target = distance / (1.4 * q.real_speed)
                time_until_buff_runs_out = target.buff_duration_remain / 22.4
                time_to_generate_energy = max(0.0, 25 - q.energy) / (22.4 * ENERGY_GENERATION_RATE)
                time_until_order = max(time_until_buff_runs_out, time_to_generate_energy)
                if time_until_order == 0:
                    return UseAbility(AbilityId.EFFECT_INJECTLARVA, target=target)
                elif time_until_order < time_to_reach_target:
                    return Move(target.position)
            return None

        def micro_queen(q: Unit) -> Action | None:
            if action := self.transfuse.transfuse_with(q):
                return action
            elif not self.bot.mediator.is_position_safe(grid=self.bot.mediator.get_ground_grid, position=q.position):
                return combat.fight_with(q)
            elif (action := inject_with_queen(q)) or (
                should_spread_creep and (action := self.creep_spread.spread_with(q))
            ):
                return action
            elif not self.bot.has_creep(q):
                return combat.retreat_to_creep(q)
            else:
                return None

        def micro_overseers(overseers: Units) -> Mapping[Unit, Action]:
            if not overseers:
                return {}

            detection_range = overseers[0].detect_range

            targets = enemy_combatants or self.bot.enemy_units

            distance = pairwise_distances(
                [a.position for a in overseers],
                [b.position for b in targets],
            )
            if overseers.amount > 1 and targets:
                second_smallest_distances = np.partition(distance, kth=1, axis=0)[1, :]
                second_smallest_distances = np.minimum(second_smallest_distances, 2.0 * detection_range)
                second_smallest_distances = np.repeat(second_smallest_distances[None, :], len(overseers), axis=0)
                cost = distance - second_smallest_distances
            else:
                cost = distance

            assignment = distribute(overseers, targets, cost)

            def micro_overseer(u: Unit) -> Action | None:
                is_safe = self.bot.mediator.is_position_safe(grid=self.bot.mediator.get_air_grid, position=u.position)
                if action := spawn_changeling(u):
                    return action
                elif not is_safe:
                    return combat.retreat_with(u)
                elif target := assignment.get(u):
                    target_point = self.bot.mediator.find_path_next_point(
                        start=u.position,
                        target=target.position,
                        grid=self.bot.mediator.get_air_grid,
                        smoothing=True,
                    )
                    return Move(target_point)
                return search_with(u)

            return {u: a for u in overseers if (a := micro_overseer(u))}

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

        def micro_overlord(u: Unit) -> Action | None:
            if not self.bot.mediator.is_position_safe(grid=self.bot.mediator.get_air_grid, position=u.position):
                return combat.retreat_with(u)
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
            UnitTypeId.QUEEN: micro_queen,
        }

        def micro_unit(u: Unit) -> Action | None:
            if (handler := micro_handlers.get(u.type_id)) and (action := handler(u)):
                return action
            return combat.fight_with(u) or search_with(u)

        def spawn_changeling(unit: Unit) -> Action | None:
            if (
                self.bot.mediator.get_cached_ground_grid[to_point(unit.position)] == np.inf
                or unit.energy < ENERGY_COST[AbilityId.SPAWNCHANGELING_SPAWNCHANGELING]
            ):
                return None
            return UseAbility(AbilityId.SPAWNCHANGELING_SPAWNCHANGELING)

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

        overseers = self.bot.units(UnitTypeId.OVERSEER)
        scout_actions = self.scout.on_step(overseers)

        actions = {
            **build_order_actions,
            **{u: a for u in harvesters if (a := micro_harvester(u))},
            **micro_overseers(overseers),
            **scout_actions,
            **{u: a for u in self.bot.units(UnitTypeId.OVERLORD) if (a := micro_overlord(u))},
            **{u: a for u in self.bot.units(CHANGELINGS) if (a := search_with(u))},
            **{u: a for u in combatants if (a := micro_unit(u))},
            **{
                u: UseAbility(AbilityId.CANCEL)
                for u in self.bot.structures
                if not u.is_ready and u.health_percentage < 0.1
            },
            **macro_actions,
        }

        if self.bot.actual_iteration == 1:
            for unit in self.bot.units(UnitTypeId.OVERLORD):
                actions[unit] = self._send_overlord_scout(unit)

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
