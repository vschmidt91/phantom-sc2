
from typing import Union, Iterable, Dict

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId

from .hatch_first import HatchFirst

class Muta(HatchFirst):
    
    def update(self) -> None:

        super().update()

        if self.ai.time < 350:

            for key in {
                UnitTypeId.ROACH,
                UnitTypeId.ZERGLING,
                UnitTypeId.RAVAGER,
                UnitTypeId.ROACHWARREN,
                UnitTypeId.HYDRALISK,
                UnitTypeId.HYDRALISKDEN,
                UnitTypeId.EVOLUTIONCHAMBER,
            }:
                if key in self.ai.composition:
                    del self.ai.composition[key]

            if 1 <= self.ai.count(UpgradeId.ZERGLINGMOVEMENTSPEED, include_planned=False):
                self.ai.composition[UnitTypeId.LAIR] = 1
                
                # self.ai.composition[UnitTypeId.SPIRE] = 1
                # self.ai.composition[UnitTypeId.MUTALISK] = self.ai.composition[UnitTypeId.DRONE] // 2