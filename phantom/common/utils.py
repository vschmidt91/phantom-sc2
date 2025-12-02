import math
from collections import Counter
from collections.abc import Iterable, Sequence
from functools import cache

import numpy as np
import skimage.draw
from ares import ALL_STRUCTURES
from loguru import logger
from sc2.dicts.unit_research_abilities import RESEARCH_INFO
from sc2.dicts.unit_tech_alias import UNIT_TECH_ALIAS
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.unit_unit_alias import UNIT_UNIT_ALIAS
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit
from sklearn.metrics import pairwise_distances as pairwise_distances_sklearn

RNG = np.random.default_rng(42)


def count_sorted[T](items: Iterable[T]) -> dict[T, int]:
    return dict(sorted(Counter(items).items()))


type Point = tuple[int, int]
type MacroId = UnitTypeId | UpgradeId


def to_point(p: Sequence[float]) -> Point:
    return int(p[0]), int(p[1])


def rectangle_perimeter(start: Point, end: Point) -> Iterable[Point]:
    i1, j1 = start
    i2, j2 = end

    for i in range(i1, i2 + 1):
        yield i, j1
        yield i, j2

    for j in range(j1 + 1, j2):
        yield i1, j
        yield i2, j


def structure_perimeter(s: Unit) -> Iterable[Point]:
    if s.is_flying:
        return
    half_extent = s.footprint_radius
    if s.position is None or half_extent is None:
        logger.error(f"cannot setup structure perimeter for {s} at position {s.position} with footprint {half_extent}")
        return
    start = np.subtract(s.position, half_extent).astype(int) - 1
    end = np.add(s.position, half_extent).astype(int)

    yield from rectangle_perimeter(start, end)


def pairwise_distances(a, b=None):
    if not a:
        return np.array([[]])
    if isinstance(b, list) and not any(b):
        return np.array([[]])
    return pairwise_distances_sklearn(a, b, ensure_all_finite=False)


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
    if distance > 0 and abs(radius1 - radius2) <= distance <= radius1 + radius2:
        disc = (radius1**2 - radius2**2 + distance**2) / (2 * distance)
        height = math.sqrt(radius1**2 - disc**2)
        middle = position1 + (disc / distance) * p01
        orthogonal = (height / distance) * np.array([p01.y, -p01.x])
        yield middle + orthogonal
        yield middle - orthogonal


def center(points: Iterable[Point]) -> Point2:
    x_sum = 0.0
    y_sum = 0.0
    num_points = 0
    for point in points:
        x_sum += point[0]
        y_sum += point[1]
        num_points += 1
    x_sum /= num_points
    y_sum /= num_points
    return Point2((x_sum, y_sum))


def line(x0: int, y0: int, x1: int, y1: int) -> list[Point]:
    lx, ly = skimage.draw.line(x0, y0, x1, y1)
    return [(int(x), int(y)) for x, y in zip(lx, ly, strict=False)]


def circle_perimeter(x0: int, y0: int, r: int, shape: tuple) -> list[Point]:
    assert len(shape) == 2
    tx, ty = skimage.draw.circle_perimeter(x0, y0, r, shape=shape)
    return [(int(x), int(y)) for x, y in zip(tx, ty, strict=False)]


def circle(x0: int, y0: int, r: int, shape: Point) -> list[Point]:
    assert len(shape) == 2
    tx, ty = skimage.draw.ellipse(x0, y0, r, r, shape=shape)
    return [(int(x), int(y)) for x, y in zip(tx, ty, strict=False)]


def rectangle(start: Point, extent: Point, shape: Point) -> tuple[np.ndarray, np.ndarray]:
    assert len(shape) == 2
    rx, ry = skimage.draw.rectangle(start, extent=extent, shape=shape)
    return rx.astype(int).flatten(), ry.astype(int).flatten()


def sample_bilinear(a, coords):
    coords = np.asarray(coords, dtype=float)
    if coords.ndim == 1:
        coords = coords[None, :]
    coords0 = coords.astype(int)
    coords0 = np.clip(coords0, 0, np.asarray(a.shape) - 2)
    coords1 = coords0 + 1
    weights0 = coords1 - coords
    weights1 = 1.0 - weights0
    values00 = a[coords0[:, 0], coords0[:, 1]]
    values01 = a[coords0[:, 0], coords1[:, 1]]
    values10 = a[coords1[:, 0], coords0[:, 1]]
    values11 = a[coords1[:, 0], coords1[:, 1]]
    values = sum(
        (
            values00 * weights0[:, 0] * weights0[:, 1],
            values01 * weights0[:, 0] * weights1[:, 1],
            values10 * weights1[:, 0] * weights0[:, 1],
            values11 * weights1[:, 0] * weights1[:, 1],
        )
    )
    return values


def get_requirements(item: MacroId, visited: set[MacroId] | None = None) -> Iterable[MacroId]:
    visited = visited or set[MacroId]()
    if item in visited:
        return
    visited.add(item)
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

    requirements = {info.get("required_building"), info.get("required_upgrade")} - {None}

    for requirement1 in requirements:
        yield requirement1
        yield from get_requirements(requirement1, visited)


@cache
def disk(radius: float) -> tuple[np.ndarray, np.ndarray]:
    r = int(radius + 0.5)
    p = radius, radius
    n = 2 * r + 1
    dx, dy = skimage.draw.disk(center=p, radius=radius, shape=(n, n))
    return dx - r, dy - r


# Bunker values assume 4 marines inside
GROUND_DPS_OVERRIDE = {
    UnitTypeId.BANELING: 16.0,
    UnitTypeId.BATTLECRUISER: 49.8 / 1.4,
    UnitTypeId.BUNKER: 4 * 7.0,
    UnitTypeId.ORACLE: 24.4 / 1.4,
    UnitTypeId.SENTRY: 8.4 / 1.4,
    UnitTypeId.VOIDRAY: 12.0,
}

GROUND_RANGE_OVERRIDE = {
    UnitTypeId.BANELING: 2.2,
    UnitTypeId.BATTLECRUISER: 6.0,
    UnitTypeId.BUNKER: 5.0,
    UnitTypeId.ORACLE: 4.0,
    UnitTypeId.SENTRY: 5.0,
    UnitTypeId.VOIDRAY: 12.0,
}

AIR_DPS_OVERRIDE = {
    UnitTypeId.BATTLECRUISER: 31.1 / 1.4,
    UnitTypeId.BUNKER: 4 * 7.0,
    UnitTypeId.SENTRY: 8.4 / 1.4,
    UnitTypeId.VOIDRAY: 6.0,
}

AIR_RANGE_OVERRIDE = {
    UnitTypeId.BATTLECRUISER: 6.0,
    UnitTypeId.BUNKER: 5.0,
    UnitTypeId.SENTRY: 5.0,
    UnitTypeId.VOIDRAY: 6.0,
}


def ground_dps_of(unit: Unit) -> float:
    return GROUND_DPS_OVERRIDE.get(unit.type_id, unit.ground_dps)


def air_dps_of(unit: Unit) -> float:
    return AIR_DPS_OVERRIDE.get(unit.type_id, unit.air_dps)


def ground_range_of(unit: Unit) -> float:
    return GROUND_RANGE_OVERRIDE.get(unit.type_id, unit.ground_range)


def air_range_of(unit: Unit) -> float:
    return AIR_RANGE_OVERRIDE.get(unit.type_id, unit.air_range)


def range_vs(unit: Unit, vs: Unit) -> float:
    if vs.is_flying:
        return air_range_of(unit)
    else:
        return ground_range_of(unit)


def dps_vs(unit: Unit, vs: Unit) -> float:
    if vs.is_flying:
        return air_dps_of(unit)
    else:
        return ground_dps_of(unit)


ALL_TRAINABLE = set(ALL_STRUCTURES | UNIT_TRAINED_FROM.keys() | UNIT_TECH_ALIAS.keys() | UNIT_UNIT_ALIAS.keys())
