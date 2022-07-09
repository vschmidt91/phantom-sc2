import inspect
import math
import time
from typing import Iterable, Union

import numpy as np
from sc2.dicts.unit_research_abilities import RESEARCH_INFO
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit


class PlacementNotFoundException(Exception):
    pass


class VersionConflictException(Exception):
    pass


async def run_timed(steps, **args):
    timings = {}
    for step in steps:
        start = time.perf_counter()
        result = step(**args)
        if inspect.isawaitable(result):
            result = await result
        end = time.perf_counter()
        timings[step.__name__] = end - start
    return timings


def center(points: Iterable[Point2]) -> Point2:
    x_sum = 0
    y_sum = 0
    num_points = 0
    for point in points:
        x_sum += point.position[0]
        y_sum += point.position[1]
        num_points += 1
    x_sum /= num_points
    y_sum /= num_points
    return Point2((x_sum, y_sum))

def is_large(unit: Unit) -> bool:
    return 2 <= unit.radius

def has_capacity(unit: Unit) -> bool:
    if unit.is_structure:
        if unit.has_reactor:
            return len(unit.orders) < 2
        else:
            return unit.is_idle
    else:
        return True


def unit_value(unit: Unit, target=None):
    if unit.is_hallucination:
        return 0
    # assume bunkers have 4 marines in them
    # if unit.type_id == UnitTypeId.BUNKER and unit.is_ready:
    #     dps = 4 * 10
    # el
    # HACK: ignore Planetary Fortresses for now
    if unit.type_id == UnitTypeId.PLANETARYFORTRESS:
        return 100
    if target is None:
        dps = max(unit.air_dps, unit.ground_dps)
    else:
        dps = unit.calculate_dps_vs_target(target)
    return dps * (unit.health + unit.shield)


def time_to_reach(unit: Unit, target: Point2) -> float:
    distance = unit.position.distance_to(target)
    movement_speed = 1.4 * unit.movement_speed
    if movement_speed == 0:
        return np.inf
    return distance / movement_speed


def get_requirements(item: Union[UnitTypeId, UpgradeId]) -> Iterable[Union[UnitTypeId, UpgradeId]]:
    if isinstance(item, UnitTypeId):
        trainers = UNIT_TRAINED_FROM[item]
        trainer = sorted(trainers, key=lambda v: v.value)[0]
        yield trainer
        info = TRAIN_INFO[trainer][item]
    elif isinstance(item, UpgradeId):
        researcher = UPGRADE_RESEARCHED_FROM[item]
        yield researcher
        info = RESEARCH_INFO[researcher][item]
    else:
        raise TypeError()

    requirements = {
        info.get("required_building"),
        info.get("required_upgrade")
    }
    requirements.discard(None)

    for requirement1 in requirements:
        yield requirement1
        for requirement2 in get_requirements(requirement1):
            yield requirement2


def flood_fill(boundary: np.ndarray, origins: Iterable[Point2]):
    front = set(origins)
    offsets = [Point2((dx, dy)) for dx in range(-1, 2) for dy in range(-1, 2)]
    offsets.remove((0, 0))
    offsets.sort(key=np.linalg.norm)

    distance = np.full(boundary.shape, math.inf)
    for origin in origins:
        distance[origin] = 0

    while front:
        next_front = set()
        for point in front:
            point_distance = distance[point]
            for offset in offsets:
                offset_norm = np.linalg.norm(offset)
                if not offset_norm:
                    continue
                neighbour = point + offset
                neighbour_distance = point_distance + offset_norm
                if neighbour in origins:
                    continue
                if boundary[neighbour]:
                    continue
                if distance[neighbour] <= neighbour_distance:
                    continue
                distance[neighbour] = neighbour_distance
                next_front.add(neighbour)
        front = next_front

    return distance
