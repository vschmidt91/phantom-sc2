

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from .macro_target import MacroTarget


ROACH_RUSH = [
    UnitTypeId.DRONE,
    UnitTypeId.OVERLORD,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.SPAWNINGPOOL,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.EXTRACTOR,
    UnitTypeId.HATCHERY,
    UnitTypeId.QUEEN,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.ROACHWARREN,
    UnitTypeId.OVERLORD,
    UnitTypeId.ROACH,
    UnitTypeId.ROACH,
    UnitTypeId.ROACH,
    UnitTypeId.ROACH,
    UnitTypeId.ROACH,
    UnitTypeId.ROACH,
    UnitTypeId.ROACH,
    UnitTypeId.ROACH,
    UnitTypeId.EXTRACTOR,
]

HATCH17 = [
    UnitTypeId.DRONE,
    UnitTypeId.OVERLORD,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.HATCHERY,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.EXTRACTOR,
    UnitTypeId.SPAWNINGPOOL,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.OVERLORD,
    UnitTypeId.ZERGLING,
    UnitTypeId.ZERGLING,
    UpgradeId.ZERGLINGMOVEMENTSPEED,
]

POOL16 = [
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.OVERLORD,
    UnitTypeId.DRONE,
    UnitTypeId.EXTRACTOR,
    UnitTypeId.DRONE,
    UnitTypeId.SPAWNINGPOOL,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.HATCHERY,
    UnitTypeId.DRONE,
    UnitTypeId.EXTRACTOR,
    UnitTypeId.QUEEN,
    UnitTypeId.ZERGLING,
    UnitTypeId.ZERGLING,
    UnitTypeId.ZERGLING,
    UnitTypeId.OVERLORD,
]

POOL12 = [
    UnitTypeId.SPAWNINGPOOL,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.OVERLORD,
    UnitTypeId.ZERGLING,
    UnitTypeId.ZERGLING,
    UnitTypeId.ZERGLING,
    UnitTypeId.HATCHERY,
    UnitTypeId.QUEEN,
    UnitTypeId.ZERGLING,
    UnitTypeId.ZERGLING,
    UnitTypeId.OVERLORD,
]