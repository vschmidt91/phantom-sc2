from collections import defaultdict
from collections.abc import Mapping, Sequence

import numpy as np
from ares import ManagerMediator, UnitTreeQueryType
from loguru import logger
from sc2.position import Point2
from sc2.unit import Unit

from phantom.common.constants import MAX_UNIT_RADIUS, MIN_WEAPON_COOLDOWN
from phantom.common.distribute import distribute
from phantom.common.utils import air_dps_of, air_range_of, ground_dps_of, ground_range_of, pairwise_distances


def medoid(points: Sequence[Point2]) -> Point2:
    distances = pairwise_distances(points)
    medoid_index = distances.sum(axis=1).argmin()
    return points[medoid_index]


def get_shootable_targets(mediator: ManagerMediator, units: Sequence[Unit]) -> Mapping[Unit, Sequence[Unit]]:
    units_filtered = list(filter(lambda u: ground_range_of(u) >= 2 and u.weapon_cooldown <= MIN_WEAPON_COOLDOWN, units))

    points_ground = list[Unit]()
    points_air = list[Unit]()
    distances_ground = list[float]()
    distances_air = list[float]()
    for unit in units_filtered:
        base_range = unit.radius + MAX_UNIT_RADIUS
        if unit.can_attack_ground:
            points_ground.append(unit)
            distances_ground.append(base_range + ground_range_of(unit))
        if unit.can_attack_air:
            points_air.append(unit)
            distances_air.append(base_range + air_range_of(unit))

    ground_candidates = mediator.get_units_in_range(
        start_points=points_ground,
        distances=distances_ground,
        query_tree=UnitTreeQueryType.EnemyGround,
        return_as_dict=True,
    )
    air_candidates = mediator.get_units_in_range(
        start_points=points_air,
        distances=distances_air,
        query_tree=UnitTreeQueryType.EnemyFlying,
        return_as_dict=True,
    )
    targets = defaultdict[Unit, list[Unit]](list)
    for unit in units_filtered:
        for target in ground_candidates.get(unit.tag, []):
            if unit.distance_to(target) <= unit.radius + ground_range_of(unit) + target.radius:
                targets[unit].append(target)
        for target in air_candidates.get(unit.tag, []):
            if unit.distance_to(target) <= unit.radius + air_range_of(unit) + target.radius:
                targets[unit].append(target)
    targets_sorted = {unit: sorted(ts, key=lambda u: u.tag) for unit, ts in targets.items()}
    return targets_sorted


def time_to_attack(mediator: ManagerMediator, units: Sequence[Unit], enemies: Sequence[Unit]) -> np.ndarray:
    if not any(units) or not any(enemies):
        return np.array([])

    ground_range = np.array([ground_range_of(u) for u in units])
    air_range = np.array([air_range_of(u) for u in units])
    radius = np.array([u.radius for u in units])
    enemy_radius = np.array([u.radius for u in enemies])

    def is_attackable(u: Unit) -> bool:
        if u.is_burrowed or u.is_cloaked:
            return mediator.get_is_detected(unit=u, by_enemy=u.is_mine)
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

    movement_speed = np.array([1.4 * u.real_speed for u in units])
    movement_speed = np.repeat(movement_speed[:, None], len(enemies), axis=1)

    result = np.nan_to_num(np.divide(distances, movement_speed), nan=np.inf)
    return result


def time_to_kill(mediator: ManagerMediator, units: Sequence[Unit], enemies: Sequence[Unit]) -> np.ndarray:
    if not any(units) or not any(enemies):
        return np.array([])

    ground_dps = np.array([ground_dps_of(u) for u in units])
    air_dps = np.array([air_dps_of(u) for u in units])

    def is_attackable(u: Unit) -> bool:
        if u.is_burrowed or u.is_cloaked:
            return mediator.get_is_detected(unit=u, by_enemy=u.is_mine)
        return True

    enemy_attackable = np.array([1.0 if is_attackable(u) else 0.0 for u in enemies])
    enemy_flying = np.array([1.0 if u.is_flying else 0.0 for u in enemies])
    enemy_ground = 1.0 - enemy_flying
    dps = np.outer(ground_dps, enemy_attackable * enemy_ground) + np.outer(air_dps, enemy_attackable * enemy_flying)

    enemy_hp = np.array([u.health + u.shield for u in enemies])
    enemy_hp = np.repeat(enemy_hp[None, :], len(units), axis=0)

    result = np.nan_to_num(np.divide(enemy_hp, dps), nan=np.inf)
    return result


def assign_targets(mediator: ManagerMediator, units: Sequence[Unit], targets: Sequence[Unit]) -> Mapping[Unit, Unit]:
    if not any(units) or not any(targets):
        return {}

    cost = time_to_attack(mediator, units, targets) + time_to_kill(mediator, units, targets)

    if np.isnan(cost).any():
        logger.error("assignment cost array contains NaN values")
        cost = np.nan_to_num(cost, nan=np.inf)

    max_assigned = len(units)

    assignment = distribute(
        units,
        targets,
        cost,
        max_assigned=max_assigned,
    )

    return assignment
