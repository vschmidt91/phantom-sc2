import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import product
from typing import TYPE_CHECKING

import numpy as np
import scipy.optimize
from ares import WORKER_TYPES
from ares.consts import EngagementResult
from cython_extensions import cy_dijkstra, cy_pick_enemy_target, cy_range_vs_target
from loguru import logger
from sc2.data import Race
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2_helper.combat_simulator import CombatSimulator

from phantom.common.action import Action, Attack, HoldPosition, Move, UseAbility
from phantom.common.constants import COMBATANT_STRUCTURES, HALF, MIN_WEAPON_COOLDOWN
from phantom.common.distribute import distribute
from phantom.common.graph import graph_components
from phantom.common.utils import (
    pairwise_distances,
    sample_bilinear,
    structure_perimeter,
)
from phantom.observation import Observation
from phantom.parameters import Parameters, Prior

if TYPE_CHECKING:
    from phantom.main import PhantomBot


@dataclass(frozen=True)
class CombatPrediction:
    outcome_global: float


class CombatState:
    def __init__(self, bot: "PhantomBot", parameters: Parameters) -> None:
        self.bot = bot
        self.attacking_local = set[int]()
        self.attacking_global = True
        self.time_horizon = parameters.add(Prior(3.0, 1.0, min=0))
        self.time_horizon_enemy = parameters.add(Prior(3.0, 1.0, min=0))
        self.engagement_threshold = parameters.add(Prior(+1 / 3, 0.1, min=-1, max=1))
        self.disengagement_threshold = parameters.add(Prior(-1 / 3, 0.1, min=-1, max=1))
        self.engagement_threshold_global = parameters.add(Prior(+1 / 3, 0.1, min=-1, max=1))
        self.disengagement_threshold_global = parameters.add(Prior(-1 / 3, 0.1, min=-1, max=1))
        self.simulator = CombatSimulator()

    def step(self, observation: Observation) -> "CombatAction":
        return CombatAction(self, observation)

    def simulate(
        self,
        units: Sequence[Unit],
        enemy_units: Sequence[Unit],
        timing_adjustment: bool = True,
        attacking: bool = True,
        optimistic: bool = True,
    ) -> float:
        self.simulator.enable_timing_adjustment(timing_adjustment)

        health = sum([u.health + u.shield for u in units])
        enemy_health = sum([u.health + u.shield for u in enemy_units])

        defender = 2 if attacking else 1
        win, health_remaining = self.simulator.predict_engage(
            own_units=units,
            enemy_units=enemy_units,
            optimistic=optimistic,
            defender_player=defender,
        )
        if win:
            return health_remaining / max(1, health)
        else:
            return -health_remaining / max(1, enemy_health)


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

        self.retreat_air = cy_dijkstra(
            self.observation.bot.mediator.get_air_grid.astype(np.float64), self.retreat_targets
        )
        self.retreat_ground = cy_dijkstra(
            self.observation.bot.mediator.get_ground_grid.astype(np.float64), self.retreat_targets
        )

        self.pathing_potential = np.where(self.observation.pathing < np.inf, 0.0, 1.0)
        self.optimal_targeting = self._optimal_targeting()

        runby_targets_list = list[tuple[int, int]]()
        for s in self.observation.enemy_structures:
            runby_targets_list.extend(structure_perimeter(s))

        for w in self.observation.enemy_units(WORKER_TYPES):
            runby_targets_list.append(w.position.rounded)

        if runby_targets_list:
            runby_targets_list.extend(self.state.bot.enemy_start_locations_rounded)
            runby_targets = np.array(list(set(runby_targets_list)))
            self.runby_pathing = cy_dijkstra(
                self.observation.bot.mediator.get_ground_grid.astype(np.float64),
                runby_targets,
            )
        else:
            self.runby_pathing = None

        self.prediction = self.predict()

        if self.state.bot.enemy_race not in {Race.Zerg, Race.Random}:
            if self.prediction.outcome_global >= self.state.engagement_threshold_global.value:
                self.state.attacking_global = True
            elif self.prediction.outcome_global <= self.state.disengagement_threshold_global.value:
                self.state.attacking_global = False

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
            return CombatPrediction(trivial_outcome)

        # time_to_attack = self._time_to_attack(units, enemy_units)
        time_to_attack = self.time_to_attack
        enemy_time_to_attack = self._time_to_attack(enemy_units, units)

        # time_to_kill = self._time_to_kill(units, enemy_units)
        time_to_kill = self.time_to_kill
        enemy_time_to_kill = self._time_to_kill(enemy_units, units)

        contact = (time_to_attack < self.state.time_horizon.value) & (time_to_kill < np.inf)
        enemy_contact = (enemy_time_to_attack < self.state.time_horizon_enemy.value) & (enemy_time_to_kill < np.inf)

        contact_symmetrical = contact | enemy_contact.T

        contact_internal = np.zeros((len(units), len(units)))
        enemy_contact_internal = np.zeros((len(enemy_units), len(enemy_units)))
        adjacency_matrix = np.block(
            [[contact_internal, contact_symmetrical], [contact_symmetrical.T, enemy_contact_internal]]
        )

        clusters = graph_components(adjacency_matrix)

        outcome_global = self.state.simulate(
            units=units,
            enemy_units=enemy_units,
            attacking=self.state.attacking_global,
            timing_adjustment=False,
            optimistic=False,
        )

        all_units = [*units, *enemy_units]
        outcome_local = dict[int, EngagementResult]()
        attacking_local = dict[int, float]()
        for cluster in clusters:
            cluster_units = [all_units[i] for i in cluster]
            cluster_attacking = sum(1 for u in cluster_units if u.tag in self.state.attacking_local) / len(
                cluster_units
            )
            cluster_own = [u for u in cluster_units if u.is_mine]
            cluster_enemies = [u for u in cluster_units if u.is_enemy]
            cluster_outcome = self._predict_trivial(cluster_own, cluster_enemies) or self.state.simulate(
                units=cluster_own,
                enemy_units=cluster_enemies,
                timing_adjustment=True,
                attacking=cluster_attacking > 0.5,
                optimistic=False,
            )

            for unit in cluster_own:
                if cluster_outcome >= self.state.engagement_threshold.value:
                    self.state.attacking_local.add(unit.tag)
                elif cluster_outcome <= self.state.disengagement_threshold.value:
                    self.state.attacking_local.discard(unit.tag)

            outcome_local.update({u.tag: cluster_outcome for u in cluster_units})
            attacking_local.update({u.tag: cluster_attacking for u in cluster_units})

        return CombatPrediction(outcome_global)

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
        if not (target := self.optimal_targeting.get(baneling)):
            return None
        return UseAbility(AbilityId.ATTACK, target.position)

    def fight_with(self, unit: Unit) -> Action | None:
        p = tuple(unit.position.rounded)

        def potential_kiting(x: np.ndarray) -> float:
            if not unit.is_flying:
                pathing = sample_bilinear(self.pathing_potential, x)
                if pathing > 0.1:
                    return 1e10 * pathing

            def g(u: Unit):
                unit_range = cy_range_vs_target(unit=unit, target=u)
                safety_margin = u.movement_speed * 1.0
                enemy_range = cy_range_vs_target(unit=u, target=unit)
                d = np.linalg.norm(x - u.position) - u.radius - unit.radius
                if enemy_range < unit_range and d < safety_margin + enemy_range:
                    return safety_margin + enemy_range - d
                # elif unit_range < d < enemy_range:
                #     return d - unit_range
                return 0.0

            return sum(g(u) for u in self.enemy_combatants)

        if not (target := self.optimal_targeting.get(unit)):
            return None

        attack_ready = unit.weapon_cooldown <= MIN_WEAPON_COOLDOWN

        if attack_ready and (targets := self.observation.shootable_targets.get(unit)):
            target = cy_pick_enemy_target(enemies=targets)
            if unit.ground_range < 2:
                return Attack(target.position)
            else:
                return Attack(target)

        if not attack_ready and unit.ground_range >= 2:
            gradient = scipy.optimize.approx_fprime(unit.position, potential_kiting)
            gradient_norm = np.linalg.norm(gradient)
            if gradient_norm > 1e-5:
                return Move(unit.position - 2 * gradient / gradient_norm)

        if self.runby_pathing:
            runby_target = Point2(self.runby_pathing.get_path(unit.position, 4)[-1]).offset(HALF)
        else:
            runby_target = None

        if unit.type_id in {UnitTypeId.BANELING}:
            return Move(target.position)

        if not unit.is_flying and not self.state.attacking_global and not self.observation.creep[p]:
            return self.retreat_with(unit)

        retreat_grid = (
            self.state.bot.mediator.get_air_grid if unit.is_flying else self.state.bot.mediator.get_ground_grid
        )

        if unit.tag in self.state.attacking_local:
            should_runby = not self.observation.creep[p]
            if should_runby and unit.can_attack_ground and runby_target:
                return Attack(runby_target)
            elif unit.ground_range < 2:
                return Attack(target.position)
            else:
                return Attack(target)
        else:
            if self.observation.bot.mediator.is_position_safe(
                grid=retreat_grid,
                position=unit.position,
            ):
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

        ground_dps = np.array([u.ground_dps for u in units])
        air_dps = np.array([u.air_dps for u in units])

        def is_attackable(u: Unit) -> bool:
            if u.is_burrowed or u.is_cloaked:
                return self.observation.bot.mediator.get_is_detected(unit=u, by_enemy=u.is_mine)
            return True

        enemy_attackable = np.array([1.0 if is_attackable(u) else 0.0 for u in enemies])
        enemy_flying = np.array([1.0 if u.is_flying else 0.0 for u in enemies])
        enemy_ground = 1.0 - enemy_flying
        dps = np.outer(ground_dps, enemy_attackable * enemy_ground) + np.outer(air_dps, enemy_attackable * enemy_flying)

        enemy_hp = np.array([u.health + u.shield for u in enemies])
        enemy_hp = np.repeat(enemy_hp[np.newaxis, :], len(units), axis=0)

        time_to_kill = np.divide(enemy_hp, dps)
        return time_to_kill

    def _time_to_attack(self, units: Sequence[Unit], enemies: Sequence[Unit]) -> np.ndarray:
        if not any(units) or not any(enemies):
            return np.array([])

        ground_range = np.array([u.ground_range for u in units])
        air_range = np.array([u.air_range for u in units])
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
        distances -= np.repeat(radius[:, np.newaxis], len(enemies), axis=1)
        distances -= np.repeat(enemy_radius[np.newaxis, :], len(units), axis=0)
        distances = np.maximum(distances, 0.0)

        movement_speed = np.array([u.movement_speed for u in units])
        movement_speed = np.repeat(movement_speed[:, np.newaxis], len(enemies), axis=1)

        time_to_attack = np.divide(distances, movement_speed)
        return time_to_attack

    def _optimal_targeting(self) -> Mapping[Unit, Unit]:
        units = self.combatants
        enemies = self.enemy_combatants

        if not any(units) or not any(enemies):
            return {}

        # cost = self._time_to_attack(units, enemies) + self._time_to_kill(units, enemies)
        cost = self.time_to_attack + self.time_to_kill
        cost = np.nan_to_num(cost, nan=np.inf)

        if self.state.bot.is_micro_map:
            max_assigned = None
        elif enemies:
            optimal_assigned = len(units) / len(enemies)
            medium_assigned = math.sqrt(len(units))
            max_assigned = math.ceil(max(medium_assigned, optimal_assigned))
        else:
            max_assigned = 1

        assignment = distribute(
            units,
            enemies,
            cost,
            max_assigned=max_assigned,
        )

        return assignment
