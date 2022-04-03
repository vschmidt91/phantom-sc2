
from typing import Union, Iterable, Dict

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId

from .hatch_first import HatchFirst

class FastLair(HatchFirst):
    
    def update(self) -> None:

        super().update()
        
        if 1 <= self.ai.count(UpgradeId.ZERGLINGMOVEMENTSPEED, include_planned=False):
            self.ai.composition[UnitTypeId.LAIR] = 1