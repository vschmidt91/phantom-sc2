
from sc2.ids.unit_typeid import UnitTypeId

from sc2.unit import Unit
from sc2.data import Alliance, Result, race_townhalls, race_worker
from sc2.position import Point2
from sc2.constants import EQUIVALENTS_FOR_TECH_PROGRESS

from reserve import Reserve

CHANGELINGS = {
    UnitTypeId.CHANGELING,
    UnitTypeId.CHANGELINGMARINE,
    UnitTypeId.CHANGELINGMARINESHIELD,
    UnitTypeId.CHANGELINGZERGLING,
    UnitTypeId.CHANGELINGZERGLINGWINGS,
    UnitTypeId.CHANGELINGZEALOT,
}

def canAttack(a, b):
    return a.distance_to(b) < a.air_range if b.is_flying else a.ground_range

def makeUnique(a):
    b = []
    for x in a:
        # check if exists in unq_list
        if x not in b:
            b.append(x)
    return b

def armyValue(group):
    return sum([max(u.air_dps, u.ground_dps) * (u.shield + u.health) for u in group])

def center(group):
    xs = sum((u.position[0] for u in group)) / group.amount
    ys = sum((u.position[1] for u in group)) / group.amount
    return Point2((xs, ys))

def withEquivalents(unit):
    if unit in EQUIVALENTS_FOR_TECH_PROGRESS:
        return { unit } | EQUIVALENTS_FOR_TECH_PROGRESS[unit]
    else:
        return { unit }

def filterArmy(units):
    units = units.filter(lambda u: 0 < u.air_dps + u.ground_dps)
    units = units.exclude_type({ UnitTypeId.DRONE, UnitTypeId.PROBE, UnitTypeId.SCV })
    units = units.exclude_type({ UnitTypeId.QUEEN })
    units = units.exclude_type(CHANGELINGS)
    return units

def dot(x, y):
    return sum((xi * yi for xi, yi in zip(x, y)))