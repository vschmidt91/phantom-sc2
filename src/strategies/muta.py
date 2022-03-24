
from typing import Union, Iterable, Dict

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId

from .hatch_first import HatchFirst

class Muta(HatchFirst):
    
    def update(self) -> None:
        super().update()
        self.ai.build_spines = True
        if UnitTypeId.ROACH in self.ai.composition:
            del self.ai.composition[UnitTypeId.ROACH]
        if UnitTypeId.RAVAGER in self.ai.composition:
            del self.ai.composition[UnitTypeId.RAVAGER]
        if UnitTypeId.HYDRALISK in self.ai.composition:
            del self.ai.composition[UnitTypeId.HYDRALISK]
        if 2 <= self.ai.count(UnitTypeId.QUEEN, include_planned=False):
            self.ai.composition[UnitTypeId.LAIR] = 1
        if 1 <= self.ai.count(UnitTypeId.LAIR, include_planned=False):
            self.ai.composition[UnitTypeId.MUTALISK] = self.ai.composition[UnitTypeId.DRONE] // 3
        if UnitTypeId.ZERGLING in self.ai.composition and 1 <= self.ai.count(UnitTypeId.SPIRE, include_planned=False, include_pending=False):
            del self.ai.composition[UnitTypeId.ZERGLING]
        # composition[UnitTypeId.ZERGLING] = 2
        # composition.pop(UnitTypeId.ROACH, 0)
        # composition.pop(UnitTypeId.RAVAGER, 0)

    def filter_upgrade(self, upgrade) -> bool:
        if upgrade == UpgradeId.ZERGLINGMOVEMENTSPEED and self.ai.count(UnitTypeId.SPIRE, include_planned=False) < 1:
            return False
        return super().filter_upgrade(upgrade)