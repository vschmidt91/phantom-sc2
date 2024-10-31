from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit

from .unit import ResourceUnit

RICH_GAS = {
    UnitTypeId.RICHVESPENEGEYSER,
}


class VespeneGeyser(ResourceUnit):
    def __init__(self, unit: Unit) -> None:
        super().__init__(unit)
        self.structure: Unit | None = None

    @property
    def is_rich(self) -> bool:
        if not self.unit:
            return False
        else:
            return self.unit.type_id in RICH_GAS

    @property
    def remaining(self) -> int:
        if not self.unit:
            return 0
        elif not self.unit.is_visible:
            return 2250
        else:
            return self.unit.vespene_contents

    @property
    def harvester_target(self) -> int:
        return 3 if self.structure and self.structure.is_ready and self.remaining else 0

    @property
    def target_unit(self) -> Unit | None:
        return self.structure if self.structure else None
