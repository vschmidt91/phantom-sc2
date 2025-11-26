from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from ares import UnitTreeQueryType
from cython_extensions import cy_dijkstra, cy_pick_enemy_target
from loguru import logger
from sc2.data import Race
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit
from scipy.optimize import approx_fprime

from phantom.common.action import Action, Attack, HoldPosition, Move, UseAbility
from phantom.common.constants import (
    CIVILIANS,
    COMBATANT_STRUCTURES,
    ENEMY_CIVILIANS,
    HALF,
    MAX_UNIT_RADIUS,
    MIN_WEAPON_COOLDOWN,
)
from phantom.common.distribute import distribute
from phantom.common.utils import (
    Point,
    air_dps_of,
    air_range_of,
    ground_dps_of,
    ground_range_of,
    pairwise_distances,
    range_vs,
    sample_bilinear,
    structure_perimeter,
)
from phantom.parameters import Parameters, Prior
from phantom.simulator import CombatSetup, StepwiseCombatSimulator

if TYPE_CHECKING:
    from phantom.main import PhantomBot


def medoid(points: Sequence[Point2]) -> Point2:
    distances = pairwise_distances(points)
    medoid_index = distances.sum(axis=1).argmin()
    return points[medoid_index]


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
            self.engagement_threshold_global - parameters.add(Prior(-0.3, 0.01, min=0, max=1)).value
        )
        self.attacking_global = True
        self.attacking_local = set[int]()
        self.targeting = dict[int, Unit]()
        self.simulator = StepwiseCombatSimulator(bot)

    def step(self) -> "CombatAction":
        return CombatAction(self)


class CombatAction:
    def __init__(self, state: CombatState) -> None:
        self.state = state
        self.bot = state.bot

        self.combatants = self.bot.units.exclude_type(CIVILIANS) | self.bot.structures(COMBATANT_STRUCTURES)
        self.enemy_combatants = self.bot.enemy_units.exclude_type(ENEMY_CIVILIANS) | self.bot.enemy_structures(
            COMBATANT_STRUCTURES
        )

        self.safe_combatants = list[Unit]()
        for unit in self.combatants:
            grid = self.bot.mediator.get_air_grid if unit.is_flying else self.bot.mediator.get_ground_grid
            if self.bot.mediator.is_position_safe(
                grid=grid,
                position=unit.position,
            ):
                self.safe_combatants.append(unit)

        # retreat_to_creep_targets = list(zip(*self.bot.mediator.get_creep_edges))
        retreat_to_creep_targets = list[Point]()
        for townhall in self.bot.townhalls.ready:
            retreat_to_creep_targets.extend(structure_perimeter(townhall))
        for tumor in self.bot.structures(UnitTypeId.CREEPTUMORBURROWED):
            retreat_to_creep_targets.extend(tumor.position.rounded)
        if retreat_to_creep_targets:
            self.retreat_to_creep_pathing = cy_dijkstra(
                self.bot.mediator.get_ground_grid.astype(np.float64), np.atleast_2d(retreat_to_creep_targets)
            )
        else:
            self.retreat_to_creep_pathing = None

        retreat_targets = list()
        if self.safe_combatants:
            # retreat_targets.extend([u.position for u in self.safe_combatants])
            retreat_targets.append(medoid([u.position for u in self.safe_combatants]))

        if not retreat_targets:
            retreat_targets.extend(
                b
                for b in self.bot.bases_taken
                if self.bot.mediator.is_position_safe(
                    grid=self.bot.mediator.get_ground_grid,
                    position=Point2(b),
                )
            )

        if not retreat_targets:
            logger.warning("No retreat targets, falling back to start mineral line")
            p = self.bot.in_mineral_line[self.bot.start_location.rounded]
            retreat_targets.append(p)

        self.time_to_kill = self._time_to_kill(self.combatants, self.enemy_combatants)
        self.time_to_attack = self._time_to_attack(self.combatants, self.enemy_combatants)
        self.pathing_potential = np.where(self.bot.mediator.get_cached_ground_grid < np.inf, 0.0, 1.0)
        self.state.targeting = self._assign_targets()
        self.shootable_targets = self._shootable_targets()

        retreat_targets_array = np.atleast_2d(retreat_targets).astype(int)
        self.retreat_air = cy_dijkstra(self.bot.mediator.get_air_grid.astype(np.float64), retreat_targets_array)
        self.retreat_ground = cy_dijkstra(self.bot.mediator.get_ground_grid.astype(np.float64), retreat_targets_array)

        runby_targets = list[Point2]()
        for s in self.bot.enemy_structures:
            runby_targets.extend(map(Point2, structure_perimeter(s)))
        for w in self.bot.enemy_workers:
            runby_targets.append(w.position)
        if not runby_targets:
            runby_targets.extend(self.bot.enemy_start_locations)
        runby_targets_array = np.atleast_2d(runby_targets).astype(int)
        self.runby_pathing = cy_dijkstra(
            self.bot.mediator.get_ground_grid.astype(np.float64),
            runby_targets_array,
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
            retreat_grid = self.bot.mediator.get_air_grid if unit.is_flying else self.bot.mediator.get_ground_grid
            retreat_point = self.bot.mediator.find_closest_safe_spot(
                from_pos=unit.position,
                grid=retreat_grid,
                radius=limit,
            )
        else:
            retreat_point = Point2(retreat_path[-1]).offset(HALF)
        return Move(retreat_point)

    def retreat_to_creep(self, unit: Unit, limit=3) -> Action | None:
        if self.retreat_to_creep_pathing is None:
            return None
        path = self.retreat_to_creep_pathing.get_path(unit.position, limit=limit)
        return Move(Point2(path[-1]).offset(HALF))

    def fight_with_baneling(self, baneling: Unit) -> Action | None:
        if not (target := self.state.targeting.get(baneling.tag)):
            return None
        return UseAbility(AbilityId.ATTACK, target.position)

    def fight_with(self, unit: Unit) -> Action | None:
        ground_range = ground_range_of(unit)
        is_on_creep = self.bot.has_creep(unit) or self.bot.enemy_race == Race.Zerg
        attack_ready = unit.weapon_cooldown <= MIN_WEAPON_COOLDOWN
        grid = self.bot.mediator.get_air_grid if unit.is_flying else self.bot.mediator.get_ground_grid
        is_safe = self.bot.mediator.is_position_safe(
            grid=grid,
            position=unit.position,
        )

        def potential_kiting(x: np.ndarray) -> float:
            def g(u: Unit):
                unit_range = range_vs(unit, u)
                safety_margin = u.movement_speed * 1.0
                enemy_range = range_vs(u, unit)
                d = np.linalg.norm(x - u.position) - u.radius - unit.radius
                if enemy_range < unit_range and d < safety_margin + enemy_range:
                    return safety_margin + enemy_range - d
                return 0.0

            return sum(g(u) for u in self.enemy_combatants)

        if not unit.is_flying and not self.state.attacking_global and not is_on_creep:
            return self.retreat_to_creep(unit)

        if attack_ready and (targets := self.shootable_targets.get(unit)):
            return Attack(cy_pick_enemy_target(enemies=targets))

        if not (target := self.state.targeting.get(unit.tag)):
            return None

        if unit.tag in self.state.attacking_local:
            if (
                not attack_ready
                and ground_range >= 2
                and (
                    unit.is_flying or sample_bilinear(self.bot.mediator.get_cached_ground_grid, unit.position) < np.inf
                )
            ):
                gradient = approx_fprime(unit.position, potential_kiting)
                gradient_norm = np.linalg.norm(gradient)
                if gradient_norm > 1e-5:
                    return Move(unit.position - (2 / gradient_norm) * Point2(gradient))

            should_runby = not unit.is_flying and not is_on_creep and is_safe
            if should_runby:
                runby_target = Point2(self.runby_pathing.get_path(unit.position, 4)[-1]).offset(HALF)
                return Attack(runby_target)
            elif ground_range < 2:
                return Attack(target.position)
            else:
                return Attack(target)
        else:
            return self.retreat_with(unit)

    def do_unburrow(self, unit: Unit) -> Action | None:
        if unit.health_percentage > 0.9:
            return UseAbility(AbilityId.BURROWUP)
        elif UpgradeId.TUNNELINGCLAWS not in self.bot.state.upgrades:
            return None
        elif self.bot.mediator.get_ground_grid[unit.position.rounded] > 1:
            return self.retreat_with(unit)
        return HoldPosition()

    def do_burrow(self, unit: Unit) -> Action | None:
        if (
            UpgradeId.BURROW not in self.bot.state.upgrades
            or unit.health_percentage > 0.3
            or unit.is_revealed
            or not unit.weapon_cooldown
            or self.bot.mediator.get_is_detected(unit=unit, by_enemy=True)
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
                return self.bot.mediator.get_is_detected(unit=u, by_enemy=u.is_mine)
            return True

        enemy_attackable = np.array([1.0 if is_attackable(u) else 0.0 for u in enemies])
        enemy_flying = np.array([1.0 if u.is_flying else 0.0 for u in enemies])
        enemy_ground = 1.0 - enemy_flying
        dps = np.outer(ground_dps, enemy_attackable * enemy_ground) + np.outer(air_dps, enemy_attackable * enemy_flying)

        enemy_hp = np.array([u.health + u.shield for u in enemies])
        enemy_hp = np.repeat(enemy_hp[None, :], len(units), axis=0)

        time_to_kill = np.nan_to_num(np.divide(enemy_hp, dps), nan=np.inf)
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
                return self.bot.mediator.get_is_detected(unit=u, by_enemy=u.is_mine)
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

        time_to_attack = np.nan_to_num(np.divide(distances, movement_speed), nan=np.inf)
        return time_to_attack

    def _assign_targets(self) -> dict[int, Unit]:
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

        if np.isnan(cost).any():
            logger.error("assignment cost array contains NaN values")
            cost = np.nan_to_num(cost, nan=np.inf)

        # if self.bot.is_micro_map:
        #     max_assigned = None
        # elif enemies:
        #     optimal_assigned = len(units) / len(enemies)
        #     medium_assigned = math.sqrt(len(units))
        #     max_assigned = math.ceil(max(medium_assigned, optimal_assigned))
        # else:
        #     max_assigned = 1

        max_assigned = len(units)

        assignment = distribute(
            [u.tag for u in units],
            enemies,
            cost,
            max_assigned=max_assigned,
        )

        return dict(assignment)

    def _shootable_targets(self, bonus_range=0.0) -> Mapping[Unit, Sequence[Unit]]:
        units = self.combatants.filter(lambda u: ground_range_of(u) >= 2 and u.weapon_cooldown <= MIN_WEAPON_COOLDOWN)

        points_ground = list[Unit]()
        points_air = list[Unit]()
        distances_ground = list[float]()
        distances_air = list[float]()
        for unit in units:
            base_range = bonus_range + unit.radius + MAX_UNIT_RADIUS
            if unit.can_attack_ground:
                points_ground.append(unit)
                distances_ground.append(base_range + ground_range_of(unit))
            if unit.can_attack_air:
                points_air.append(unit)
                distances_air.append(base_range + air_range_of(unit))

        ground_candidates = self.bot.mediator.get_units_in_range(
            start_points=points_ground,
            distances=distances_ground,
            query_tree=UnitTreeQueryType.EnemyGround,
            return_as_dict=True,
        )
        air_candidates = self.bot.mediator.get_units_in_range(
            start_points=points_air,
            distances=distances_air,
            query_tree=UnitTreeQueryType.EnemyFlying,
            return_as_dict=True,
        )
        targets = defaultdict[Unit, list[Unit]](list)
        for unit in units:
            for target in ground_candidates.get(unit.tag, []):
                if unit.distance_to(target) < bonus_range + unit.radius + ground_range_of(unit) + target.radius:
                    targets[unit].append(target)
            for target in air_candidates.get(unit.tag, []):
                if unit.distance_to(target) < bonus_range + unit.radius + air_range_of(unit) + target.radius:
                    targets[unit].append(target)
        targets_sorted = {unit: sorted(ts, key=lambda u: u.tag) for unit, ts in targets.items()}
        return targets_sorted
