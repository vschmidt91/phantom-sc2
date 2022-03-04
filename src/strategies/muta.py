
from typing import Union, Iterable, Dict

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId

from .hatch_first import HatchFirst

class Muta(HatchFirst):
    
    def composition(self, bot) -> Dict[UnitTypeId, int]:
        if 9 * 60 < bot.time:
            return super().composition(bot)
        composition = super().composition(bot)
        if UnitTypeId.ROACH in composition:
            del composition[UnitTypeId.ROACH]
        if UnitTypeId.RAVAGER in composition:
            del composition[UnitTypeId.RAVAGER]
        if UnitTypeId.HYDRALISK in composition:
            del composition[UnitTypeId.HYDRALISK]
        if 2 <= bot.count(UnitTypeId.QUEEN, include_planned=False):
            composition[UnitTypeId.LAIR] = 1
        if 1 <= bot.count(UnitTypeId.LAIR, include_planned=False):
            composition[UnitTypeId.MUTALISK] = composition[UnitTypeId.DRONE] // 2
        if 1 <= bot.count(UnitTypeId.SPIRE, include_planned=False, include_pending=False):
            del composition[UnitTypeId.ZERGLING]
        # composition[UnitTypeId.ZERGLING] = 2
        # composition.pop(UnitTypeId.ROACH, 0)
        # composition.pop(UnitTypeId.RAVAGER, 0)
        return composition