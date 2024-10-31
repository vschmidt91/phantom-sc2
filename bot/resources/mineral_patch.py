from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from .unit import ResourceUnit

RICH_MINERALS = {
    UnitTypeId.RICHMINERALFIELD,
    UnitTypeId.RICHMINERALFIELD750,
    UnitTypeId.PURIFIERRICHMINERALFIELD,
    UnitTypeId.PURIFIERRICHMINERALFIELD750,
}


class MineralPatch(ResourceUnit):
    def __init__(self, unit: Unit) -> None:
        super().__init__(unit)
        self.speedmining_target: Point2 = unit.position

    @property
    def is_rich(self) -> bool:
        if not self.unit:
            return False
        else:
            return self.unit.type_id in RICH_MINERALS

    @property
    def remaining(self) -> int:
        if not self.unit:
            return 0
        elif not self.unit.is_visible:
            return 1500
        else:
            return self.unit.mineral_contents

    @property
    def harvester_target(self) -> int:
        return 2 if self.remaining else 0

    @property
    def target_unit(self) -> Unit | None:
        return self.unit
