
from typing import Iterable, Set, Tuple, Union
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

def canAttack(a, b):
    return a.distance_to(b) < 6 + (a.air_range if b.is_flying else a.ground_range)

def makeUnique(a):
    b = []
    for x in a:
        # check if exists in unq_list
        if x not in b:
            b.append(x)
    return b

def armyValue(group):
    return sum((unitValue(unit) for unit in group))

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

def unitValue(unit: Unit, target = None):
    if target is None:
        dps = max(unit.air_dps, unit.ground_dps)
    else:
        dps = unit.calculate_dps_vs_target(target)
    return dps * (unit.health + unit.shield)

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

def can_attack(unit: Unit, target: Unit) -> bool:
    if not target.can_be_attacked:
        return False
    elif target.is_flying:
        return unit.can_attack_air
    else:
        return unit.can_attack_ground

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