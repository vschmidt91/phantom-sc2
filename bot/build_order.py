from dataclasses import dataclass

from ares import UnitID


@dataclass
class BuildOrderStep:
    unit: UnitID
    count: int


@dataclass
class BuildOrder:
    steps: list[BuildOrderStep]


HATCH_FIRST = BuildOrder(
    [
        BuildOrderStep(UnitID.DRONE, 13),
        BuildOrderStep(UnitID.OVERLORD, 2),
        BuildOrderStep(UnitID.DRONE, 16),
        BuildOrderStep(UnitID.HATCHERY, 2),
        BuildOrderStep(UnitID.DRONE, 17),
        BuildOrderStep(UnitID.EXTRACTOR, 1),
        BuildOrderStep(UnitID.SPAWNINGPOOL, 1),
    ]
)
