from typing import Iterable

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


def center(points: Iterable[Point2]) -> Point2:
    x_sum = 0.0
    y_sum = 0.0
    num_points = 0
    for point in points:
        x_sum += point.position[0]
        y_sum += point.position[1]
        num_points += 1
    x_sum /= num_points
    y_sum /= num_points
    return Point2((x_sum, y_sum))


def time_to_reach(unit: Unit, target: Point2) -> float:
    distance = unit.position.distance_to(target)
    movement_speed = 1.4 * unit.movement_speed
    if movement_speed == 0:
        return np.inf
    return distance / movement_speed


def get_requirements(item: UnitTypeId | UpgradeId) -> Iterable[UnitTypeId | UpgradeId]:
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

    requirements = {info.get("required_building"), info.get("required_upgrade")}
    requirements.discard(None)

    for requirement1 in requirements:
        yield requirement1
        for requirement2 in get_requirements(requirement1):
            yield requirement2


FLOOD_FILL_OFFSETS = {
    Point2((-1, 0)),
    Point2((0, -1)),
    Point2((0, +1)),
    Point2((+1, 0)),
    # Point2((-1, -1)),
    # Point2((-1, +1)),
    # Point2((+1, -1)),
    # Point2((+1, +1)),
}


def flood_fill(weight: np.ndarray, origins: Iterable[Point2]):
    distance = np.full(weight.shape, np.inf)
    for origin in origins:
        distance[origin] = 0

    front = set(origins)
    while front:
        next_front = set()
        for point in front:
            point_distance = distance[point]
            for offset in FLOOD_FILL_OFFSETS:
                offset_norm = np.linalg.norm(offset)
                if offset_norm == 0.0:
                    continue
                neighbour = point + offset
                neighbour_distance = point_distance + offset_norm * weight[neighbour.rounded]
                if neighbour in origins:
                    continue
                if np.isinf(neighbour_distance):
                    continue
                if distance[neighbour] <= neighbour_distance:
                    continue
                distance[neighbour] = neighbour_distance
                next_front.add(neighbour)
        front = next_front

    return distance
