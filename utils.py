
from typing import Set
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.constants import EQUIVALENTS_FOR_TECH_PROGRESS

import numpy as np

CHANGELINGS = {
    UnitTypeId.CHANGELING,
    UnitTypeId.CHANGELINGMARINE,
    UnitTypeId.CHANGELINGMARINESHIELD,
    UnitTypeId.CHANGELINGZERGLING,
    UnitTypeId.CHANGELINGZERGLINGWINGS,
    UnitTypeId.CHANGELINGZEALOT,
}

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

def center(group):
    xs = sum((u.position[0] for u in group)) / group.amount
    ys = sum((u.position[1] for u in group)) / group.amount
    return Point2((xs, ys))

def withEquivalents(unit: UnitTypeId) -> Set[UnitTypeId]:
    if unit in EQUIVALENTS_FOR_TECH_PROGRESS:
        return { unit } | EQUIVALENTS_FOR_TECH_PROGRESS[unit]
    else:
        return { unit }

def unitValue(unit, target = None):
    if target is None:
        dps = max(unit.air_dps, unit.ground_dps)
    else:
        dps = unit.calculate_dps_vs_target(target)
    return dps * (unit.shield + unit.health)

def filterArmy(units):
    units = units.filter(lambda u: 0 < u.air_dps + u.ground_dps)
    units = units.exclude_type({ UnitTypeId.DRONE, UnitTypeId.PROBE, UnitTypeId.SCV })
    units = units.exclude_type({ UnitTypeId.QUEEN })
    units = units.exclude_type(CHANGELINGS)
    return units

def dot(x, y):
    return sum((xi * yi for xi, yi in zip(x, y)))

def choose_by_distance_to(choices, subject):
    w = [pow(max(1, subject.distance_to(c)), -2) for c in choices]
    ws = sum(w)
    p = [wi / ws for wi in w]
    i = np.random.choice(len(choices), p=p)
    return choices[i]