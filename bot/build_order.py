from typing import TypeAlias

from sc2.ids.unit_typeid import UnitTypeId

BuildOrderSteps: TypeAlias = list[tuple[UnitTypeId, int]]

HATCH_FIRST: BuildOrderSteps = [
    (UnitTypeId.DRONE, 13),
    (UnitTypeId.OVERLORD, 2),
    (UnitTypeId.DRONE, 16),
    (UnitTypeId.HATCHERY, 2),
    (UnitTypeId.DRONE, 17),
    (UnitTypeId.EXTRACTOR, 1),
    (UnitTypeId.SPAWNINGPOOL, 1),
]
