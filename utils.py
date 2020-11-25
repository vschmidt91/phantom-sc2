
import inspect
from sc2.ids.unit_typeid import UnitTypeId

from sc2.unit import Unit
from sc2.data import Alliance, Result, race_townhalls, race_worker
from sc2.position import Point2

from reserve import Reserve

CHANGELINGS = {
    UnitTypeId.CHANGELING,
    UnitTypeId.CHANGELINGMARINE,
    UnitTypeId.CHANGELINGMARINESHIELD,
    UnitTypeId.CHANGELINGZERGLING,
    UnitTypeId.CHANGELINGZERGLINGWINGS,
    UnitTypeId.CHANGELINGZEALOT,
}

def hasCapacity(unit: Unit) -> bool:
    if unit.type_id in race_worker.values():
        return 1
    elif unit.has_reactor:
        return len(unit.orders) < 2
    else:
        return unit.is_idle

def armyValue(group):
    return sum([max(u.air_dps, u.ground_dps) * (u.shield + u.health) for u in group])

def center(group):
    xs = sum((u.position[0] for u in group)) / group.amount
    ys = sum((u.position[1] for u in group)) / group.amount
    return Point2((xs, ys))

async def doChain(chain):
    reserve = Reserve()
    for step in chain:
        reserve = step(reserve)
        if inspect.iscoroutine(reserve):
            reserve = await reserve
    return reserve

def filterArmy(units):
    units = units.filter(lambda u: 0 < u.air_dps + u.ground_dps)
    units = units.exclude_type({ UnitTypeId.DRONE, UnitTypeId.PROBE, UnitTypeId.SCV })
    units = units.exclude_type({ UnitTypeId.QUEEN })
    units = units.exclude_type(CHANGELINGS)
    return units