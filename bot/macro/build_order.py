from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId


@dataclass(frozen=True)
class BuildOrderStep:
    unit: UnitTypeId
    count: int
    cancel: bool = False


@dataclass(frozen=True)
class BuildOrder:
    steps: list[BuildOrderStep]


OVERHATCH = BuildOrder(
    [
        BuildOrderStep(UnitTypeId.DRONE, 14),
        BuildOrderStep(UnitTypeId.EXTRACTOR, 1, cancel=True),
        BuildOrderStep(UnitTypeId.OVERLORD, 2),
        BuildOrderStep(UnitTypeId.HATCHERY, 2),
        BuildOrderStep(UnitTypeId.DRONE, 16),
        BuildOrderStep(UnitTypeId.EXTRACTOR, 1),
        BuildOrderStep(UnitTypeId.SPAWNINGPOOL, 1),
    ]
)

HATCH_FIRST = BuildOrder(
    [
        BuildOrderStep(UnitTypeId.DRONE, 13),
        BuildOrderStep(UnitTypeId.OVERLORD, 2),
        BuildOrderStep(UnitTypeId.DRONE, 16),
        BuildOrderStep(UnitTypeId.HATCHERY, 2),
        BuildOrderStep(UnitTypeId.DRONE, 17),
        BuildOrderStep(UnitTypeId.EXTRACTOR, 1),
        BuildOrderStep(UnitTypeId.SPAWNINGPOOL, 1),
    ]
)
