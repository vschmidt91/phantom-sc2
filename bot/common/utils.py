import dataclasses
import enum
import json
import math
from functools import cache
from typing import Iterable, TypeAlias

import numpy as np
import skimage.draw
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


Point: TypeAlias = tuple[int, int]


def unit_value(u: Unit, d: np.ndarray) -> float:
    return pow(u.health + u.shield, d[u.position.rounded]) * max(u.ground_dps, u.air_dps)


def can_attack(unit: Unit, target: Unit) -> bool:
    if target.is_cloaked and not target.is_revealed:
        return False
    # elif target.is_burrowed and not any(self.units_detecting(target)):
    #     return False
    elif target.is_flying:
        return unit.can_attack_air
    else:
        return unit.can_attack_ground


def project_point_onto_line(origin: Point2, direction: Point2, position: Point2) -> Point2:
    orthogonal_direction = Point2((direction[1], -direction[0]))
    return (
        position
        - np.dot(position - origin, orthogonal_direction)
        / np.dot(orthogonal_direction, orthogonal_direction)
        * orthogonal_direction
    )


def get_intersections(position1: Point2, radius1: float, position2: Point2, radius2: float) -> Iterable[Point2]:
    p01 = position2 - position1
    distance = np.linalg.norm(p01)
    if 0 < distance and abs(radius1 - radius2) <= distance <= radius1 + radius2:
        disc = (radius1**2 - radius2**2 + distance**2) / (2 * distance)
        height = math.sqrt(radius1**2 - disc**2)
        middle = position1 + (disc / distance) * p01
        orthogonal = (height / distance) * np.array([p01.y, -p01.x])
        yield middle + orthogonal
        yield middle - orthogonal


async def chain_async(*streams):
    for stream in streams:
        async for item in stream:
            yield item


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


def line(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    lx, ly = skimage.draw.line(x0, y0, x1, y1)
    return [(int(x), int(y)) for x, y in zip(lx, ly)]


def circle_perimeter(x0: int, y0: int, r: int, shape: tuple) -> list[tuple[int, int]]:
    assert len(shape) == 2
    tx, ty = skimage.draw.circle_perimeter(x0, y0, r, shape=shape)
    return [(int(x), int(y)) for x, y in zip(tx, ty)]


def circle(x0: int, y0: int, r: int, shape: tuple) -> list[tuple[int, int]]:
    assert len(shape) == 2
    tx, ty = skimage.draw.ellipse(x0, y0, r, r, shape=shape)
    return [(int(x), int(y)) for x, y in zip(tx, ty)]


def rectangle(start: tuple[int, int], extent: tuple[int, int], shape: tuple) -> tuple[np.ndarray, np.ndarray]:
    assert len(shape) == 2
    rx, ry = skimage.draw.rectangle(start, extent=extent, shape=shape)
    return rx.astype(int).flatten(), ry.astype(int).flatten()


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


@cache
def disk(radius: float) -> tuple[np.ndarray, np.ndarray]:
    r = int(radius + 0.5)
    p = radius, radius
    n = 2 * r + 1
    dx, dy = skimage.draw.disk(center=p, radius=radius, shape=(n, n))
    return dx - r, dy - r


class JSONDataclassEncoder(json.JSONEncoder):
    def default(self, o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        elif isinstance(o, enum.Enum):
            return o.value
        return super().default(o)
