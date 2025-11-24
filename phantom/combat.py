from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import product
from typing import TYPE_CHECKING

import numpy as np
from ares import WORKER_TYPES
from cython_extensions import cy_dijkstra, cy_pick_enemy_target
from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit
from scipy.optimize import approx_fprime

from phantom.common.action import Action, Attack, HoldPosition, Move, UseAbility
from phantom.common.constants import COMBATANT_STRUCTURES, HALF, MIN_WEAPON_COOLDOWN
from phantom.common.distribute import distribute
from phantom.common.utils import (
    air_dps_of,
    air_range_of,
    ground_dps_of,
    ground_range_of,
    pairwise_distances,
    range_vs,
    sample_bilinear,
    structure_perimeter,
)
from phantom.observation import Observation
from phantom.parameters import Parameters, Prior
from phantom.simulator import CombatSetup, StepwiseCombatSimulator

if TYPE_CHECKING:
    from phantom.main import PhantomBot


@dataclass(frozen=True)
class CombatPrediction:
    outcome_global: float
    outcome_local: Mapping[int, float]


class CombatState:
    def __init__(self, bot: "PhantomBot", parameters: Parameters) -> None:
        self.bot = bot
        self.engagement_threshold = parameters.add(Prior(0.0, 0.01, min=-1, max=1)).value
        self.disengagement_threshold = self.engagement_threshold - parameters.add(Prior(0.0, 0.01, min=0, max=1)).value
        self.engagement_threshold_global = parameters.add(Prior(0.0, 0.01, min=-1, max=1)).value
        self.disengagement_threshold_global = (
            self.engagement_threshold_global - parameters.add(Prior(0.0, 0.01, min=0, max=1)).value
        )
        self.attacking_global = True
        self.attacking_local = set[int]()
        self.targeting = dict[int, Unit]()
        self.simulator = StepwiseCombatSimulator(bot)

    def step(self, observation: Observation) -> "CombatAction":
        return CombatAction(self, observation)


class CombatAction:
    def __init__(self, state: CombatState, observation: Observation) -> None:
        self.state = state
        self.observation = observation

        self.enemy_values = {
            u.tag: observation.calculate_unit_value_weighted(u.type_id) for u in observation.enemy_units
        }

        if self.state.bot.is_micro_map:
            retreat_targets = list()
            for dx, dy in product([-10, 0, 10], repeat=2):
                p = observation.map_center.rounded + Point2((dx, dy))
                if observation.bot.mediator.get_ground_grid[p] == 1.0:
                    retreat_targets.append(p)
            if not retreat_targets:
                retreat_targets.append(self.observation.map_center)
        else:
            retreat_targets = list()
            for b in observation.bases_taken:
                p = self.state.bot.in_mineral_line[b]
                if state.bot.mediator.get_ground_grid[p] == 1.0:
                    retreat_targets.append(p)
            if not retreat_targets:
                combatant_positions = {
                    p
                    for u in observation.combatants
                    if state.bot.mediator.get_ground_grid[p := tuple(u.position.rounded)] == 1.0
                }
                retreat_targets.extend(combatant_positions)
            if not retreat_targets:
                logger.warning("No retreat targets, falling back to start mineral line")
                p = self.state.bot.in_mineral_line[observation.start_location.rounded]
                retreat_targets.append(p)

        self.combatants = (
            self.observation.combatants | self.observation.overseers | self.observation.structures(COMBATANT_STRUCTURES)
        )
        self.enemy_combatants = self.observation.enemy_combatants | self.observation.enemy_structures(
            COMBATANT_STRUCTURES
        )

        self.time_to_kill = self._time_to_kill(self.combatants, self.enemy_combatants)
        self.time_to_attack = self._time_to_attack(self.combatants, self.enemy_combatants)

        self.retreat_targets = np.atleast_2d(retreat_targets).astype(int)

        self.air_grid = self.observation.bot.mediator.get_air_grid
        self.ground_grid = self.observation.bot.mediator.get_ground_grid

        self.retreat_air = cy_dijkstra(self.air_grid.astype(np.float64), self.retreat_targets)
        self.retreat_ground = cy_dijkstra(self.ground_grid.astype(np.float64), self.retreat_targets)

        self.pathing_potential = np.where(self.observation.pathing < np.inf, 0.0, 1.0)
        self.state.targeting = self._assign_targets()

        runby_targets_list = list[tuple[int, int]]()
        for s in self.observation.enemy_structures:
            runby_targets_list.extend(structure_perimeter(s))

        for w in self.observation.enemy_units(WORKER_TYPES):
            runby_targets_list.append(w.position.rounded)

        if not runby_targets_list:
            runby_targets_list.extend(self.state.bot.enemy_start_locations_rounded)

        runby_targets = np.array(list(set(runby_targets_list)))
        self.runby_pathing = cy_dijkstra(
            self.ground_grid.astype(np.float64),
            runby_targets,
        )

        self.prediction = self.predict()

        if self.prediction.outcome_global >= self.state.engagement_threshold:
            self.state.attacking_global = True
        elif self.prediction.outcome_global < self.state.disengagement_threshold:
            self.state.attacking_global = False

        for tag, outcome in self.prediction.outcome_local.items():
            if outcome >= self.state.engagement_threshold:
                self.state.attacking_local.add(tag)
            elif outcome < self.state.disengagement_threshold:
                self.state.attacking_local.discard(tag)

    def _predict_trivial(self, units: Sequence[Unit], enemy_units: Sequence[Unit]) -> float | None:
        if not any(units) and not any(enemy_units):
            return 0.0
        elif not any(units):
            return -1.0
        elif not any(enemy_units):
            return +1.0
        return None

    def predict(self) -> CombatPrediction:
        units = self.combatants
        enemy_units = self.enemy_combatants

        if (trivial_outcome := self._predict_trivial(units, enemy_units)) is not None:
            return CombatPrediction(trivial_outcome, {})

        simulation = self.state.simulator.simulate(CombatSetup(units1=units, units2=enemy_units))

        return CombatPrediction(simulation.outcome_global, simulation.outcome_local)

    def retreat_with(self, unit: Unit, limit=3) -> Action | None:
        retreat_map = self.retreat_air if unit.is_flying else self.retreat_ground
        retreat_path = retreat_map.get_path(unit.position, limit=limit)
        if len(retreat_path) < limit:
            retreat_point = self.observation.find_safe_spot(
                unit.position,
                unit.is_flying,
                limit,
            )
        else:
            retreat_point = Point2(retreat_path[-1]).offset(HALF)
        return Move(retreat_point)

    def fight_with_baneling(self, baneling: Unit) -> Action | None:
        if not (target := self.state.targeting.get(baneling.tag)):
            return None
        return UseAbility(AbilityId.ATTACK, target.position)

    def fight_with(self, unit: Unit) -> Action | None:
        ground_range = ground_range_of(unit)
        p = tuple(unit.position.rounded)

        def potential_kiting(x: np.ndarray) -> float:
            def g(u: Unit):
                unit_range = range_vs(unit, u)
                safety_margin = u.movement_speed * 1.0
                enemy_range = range_vs(u, unit)
                d = np.linalg.norm(x - u.position) - u.radius - unit.radius
                if enemy_range < unit_range and d < safety_margin + enemy_range:
                    return safety_margin + enemy_range - d
                # elif unit_range < d < enemy_range:
                #     return d - unit_range
                return 0.0

            return sum(g(u) for u in self.enemy_combatants)

        if not (target := self.state.targeting.get(unit.tag)):
            return None

        attack_ready = unit.weapon_cooldown <= MIN_WEAPON_COOLDOWN

        if attack_ready and (targets := self.observation.shootable_targets.get(unit)):
            target = cy_pick_enemy_target(enemies=targets)
            if ground_range < 2:
                return Attack(target.position)
            else:
                return Attack(target)

        runby_target = Point2(self.runby_pathing.get_path(unit.position, 4)[-1]).offset(HALF)

        if unit.type_id in {UnitTypeId.BANELING}:
            return Move(target.position)

        if not unit.is_flying and not self.state.attacking_global and not self.observation.creep[p]:
            return self.retreat_with(unit)

        retreat_grid = self.air_grid if unit.is_flying else self.ground_grid
        retreat_pathing = self.retreat_air if unit.is_flying else self.retreat_ground
        is_safe = self.observation.bot.mediator.is_position_safe(
            grid=retreat_grid,
            position=unit.position,
        )

        if unit.tag in self.state.attacking_local:
            if (
                not attack_ready
                and ground_range >= 2
                and (unit.is_flying or sample_bilinear(self.pathing_potential, unit.position) < 0.1)
            ):
                gradient = approx_fprime(unit.position, potential_kiting)
                gradient_norm = np.linalg.norm(gradient)
                if gradient_norm > 1e-5:
                    return Move(unit.position - 2 * gradient / gradient_norm)
            far_from_home = not self.observation.creep[p] or (
                self.runby_pathing.distance[p] < retreat_pathing.distance[p]
            )
            should_runby = not unit.is_flying and far_from_home and is_safe and self.state.attacking_global
            if should_runby:
                return Attack(runby_target)
            elif ground_range < 2:
                return Attack(target.position)
            else:
                return Attack(target)
        else:
            if is_safe:
                return UseAbility(AbilityId.STOP)
            else:
                return self.retreat_with(unit)

    def do_unburrow(self, unit: Unit) -> Action | None:
        if unit.health_percentage > 0.9:
            return UseAbility(AbilityId.BURROWUP)
        elif UpgradeId.TUNNELINGCLAWS not in self.observation.upgrades:
            return None
        elif self.state.bot.mediator.get_ground_grid[unit.position.rounded] > 1:
            return self.retreat_with(unit)
        return HoldPosition()

    def do_burrow(self, unit: Unit) -> Action | None:
        if (
            UpgradeId.BURROW not in self.observation.upgrades
            or unit.health_percentage > 0.3
            or unit.is_revealed
            or not unit.weapon_cooldown
            or self.state.bot.mediator.get_is_detected(unit=unit, by_enemy=True)
        ):
            return None
        return UseAbility(AbilityId.BURROWDOWN)

    def _time_to_kill(self, units: Sequence[Unit], enemies: Sequence[Unit]) -> np.ndarray:
        if not any(units) or not any(enemies):
            return np.array([])

        ground_dps = np.array([ground_dps_of(u) for u in units])
        air_dps = np.array([air_dps_of(u) for u in units])

        def is_attackable(u: Unit) -> bool:
            if u.is_burrowed or u.is_cloaked:
                return self.observation.bot.mediator.get_is_detected(unit=u, by_enemy=u.is_mine)
            return True

        enemy_attackable = np.array([1.0 if is_attackable(u) else 0.0 for u in enemies])
        enemy_flying = np.array([1.0 if u.is_flying else 0.0 for u in enemies])
        enemy_ground = 1.0 - enemy_flying
        dps = np.outer(ground_dps, enemy_attackable * enemy_ground) + np.outer(air_dps, enemy_attackable * enemy_flying)

        enemy_hp = np.array([u.health + u.shield for u in enemies])
        enemy_hp = np.repeat(enemy_hp[None, :], len(units), axis=0)

        time_to_kill = np.divide(enemy_hp, dps)
        return time_to_kill

    def _time_to_attack(self, units: Sequence[Unit], enemies: Sequence[Unit]) -> np.ndarray:
        if not any(units) or not any(enemies):
            return np.array([])

        ground_range = np.array([ground_range_of(u) for u in units])
        air_range = np.array([air_range_of(u) for u in units])
        radius = np.array([u.radius for u in units])
        enemy_radius = np.array([u.radius for u in enemies])

        def is_attackable(u: Unit) -> bool:
            if u.is_burrowed or u.is_cloaked:
                return self.observation.bot.mediator.get_is_detected(unit=u, by_enemy=u.is_mine)
            return True

        enemy_attackable = np.array([1.0 if is_attackable(u) else 0.0 for u in enemies])
        enemy_flying = np.array([1.0 if u.is_flying else 0.0 for u in enemies])
        enemy_ground = 1.0 - enemy_flying

        ranges = np.outer(ground_range, enemy_attackable * enemy_ground) + np.outer(
            air_range, enemy_attackable * enemy_flying
        )

        distances = pairwise_distances(
            [u.position for u in units],
            [u.position for u in enemies],
        )
        distances -= ranges
        distances -= np.repeat(radius[:, None], len(enemies), axis=1)
        distances -= np.repeat(enemy_radius[None, :], len(units), axis=0)
        distances = np.maximum(distances, 0.0)

        movement_speed = np.array([u.movement_speed for u in units])
        movement_speed = np.repeat(movement_speed[:, None], len(enemies), axis=1)

        time_to_attack = np.divide(distances, movement_speed)
        return time_to_attack

    def _assign_targets(self) -> dict[Unit, Unit]:
        previous_targets = self.state.targeting
        units = self.combatants
        enemies = self.enemy_combatants

        if not any(units) or not any(enemies):
            return {}

        cost = self.time_to_attack.copy()

        enemy_tag_to_index = {e.tag: j for j, e in enumerate(enemies)}
        for i, unit in enumerate(units):
            if (target := previous_targets.get(unit.tag)) and (j := enemy_tag_to_index.get(target.tag)) is not None:
                cost[i, j] = 0.0

        cost += self.time_to_kill
        cost = np.nan_to_num(cost, nan=np.inf)

        # if self.state.bot.is_micro_map:
        #     max_assigned = None
        # elif enemies:
        #     optimal_assigned = len(units) / len(enemies)
        #     medium_assigned = math.sqrt(len(units))
        #     max_assigned = math.ceil(max(medium_assigned, optimal_assigned))
        # else:
        #     max_assigned = 1

        max_assigned = len(units)

        assignment = distribute(
            units.tags,
            enemies,
            cost,
            max_assigned=max_assigned,
        )

        return dict(assignment)
