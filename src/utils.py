
from math import floor
from typing import Iterable, Optional, Set, Tuple, Union
from sc2.dicts.unit_research_abilities import RESEARCH_INFO
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.constants import EQUIVALENTS_FOR_TECH_PROGRESS

import numpy as np
import math
import time
import inspect

MacroId = Union[UnitTypeId, UpgradeId]

async def run_timed(steps, args = {}):
    timings = {}
    for step in steps:
        start = time.perf_counter()
        result = step(**args)
        if inspect.isawaitable(result):
            result = await result
        end = time.perf_counter()
        timings[step.__name__] = end - start
    return timings

def can_move(unit: Unit) -> bool:
    if unit.is_burrowed:
        if unit.type_id == UnitTypeId.INFESTORBURROWED:
            return True
        elif unit.type_id == UnitTypeId.ROACHBURROWED:
            return UpgradeId.TUNNELINGCLAWS in unit._bot_object.state.upgrades
        return False
    return 0 < unit.movement_speed

def makeUnique(a):
    b = []
    for x in a:
        # check if exists in unq_list
        if x not in b:
            b.append(x)
    return b

def armyValue(group: Iterable[Unit]) -> float:
    return sum(unitValue(unit) for unit in group)

def unitPriority(unit, target = None):
    if target is None:
        dps = max(unit.air_dps, unit.ground_dps)
    else:
        dps = unit.calculate_dps_vs_target(target)
    return dps / (unit.shield + unit.health)

def center(points: Iterable[Point2]) -> Point2:
    xs = 0
    ys = 0
    n = 0
    for p in points:
        xs += p.position[0]
        ys += p.position[1]
        n += 1
    xs /= n
    ys /= n
    return Point2((xs, ys))

def is_large(unit: Unit) -> bool:
    return 2 <= unit.radius

def unitValue(unit: Unit, target = None):
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
    distance = unit.distance_to(target)
    movement_speed = 1.4 * unit.movement_speed
    if movement_speed == 0:
        return np.inf
    return distance / movement_speed

def dot(x, y):
    return sum((xi * yi for xi, yi in zip(x, y)))

def sample(choices, key=None):
    choices = list(choices)
    if key:
        w = [key(c) for c in choices]
        ws = sum(w)
        p = [wi / ws for wi in w]
        i = np.random.choice(len(choices), p=p)
        return choices[i]
    else:
        return np.random.choice(choices)

def get_requirements(item: Union[UnitTypeId, UpgradeId]) -> Iterable[Union[UnitTypeId, UpgradeId]]:

    if type(item) is UnitTypeId:
        trainers = UNIT_TRAINED_FROM[item]
        trainer = sorted(trainers, key=lambda v:v.value)[0]
        yield trainer
        info = TRAIN_INFO[trainer][item]
    elif type(item) is UpgradeId:
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

    for r in requirements:
        yield r
        for r2 in get_requirements(r):
            yield r2

def bilinear_sample(im, p):

    y, x = p
    x0 = int(floor(x))
    x1 = x0 + 1
    y0 = int(floor(y))
    y1 = y0 + 1

    x0 = np.clip(x0, 0, im.shape[1]-1)
    x1 = np.clip(x1, 0, im.shape[1]-1)
    y0 = np.clip(y0, 0, im.shape[0]-1)
    y1 = np.clip(y1, 0, im.shape[0]-1)

    Ia = im[ y0, x0 ]
    Ib = im[ y1, x0 ]
    Ic = im[ y0, x1 ]
    Id = im[ y1, x1 ]

    wa = (x1-x) * (y1-y)
    wb = (x1-x) * (y-y0)
    wc = (x-x0) * (y1-y)
    wd = (x-x0) * (y-y0)

    return wa*Ia + wb*Ib + wc*Ic + wd*Id

def flood_fill(boundary: np.ndarray, origins: Iterable[np.ndarray]):

    front = set(origins)
    offsets = [(dx, dy) for dx in range(-1, 2) for dy in range(-1, 2)]
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