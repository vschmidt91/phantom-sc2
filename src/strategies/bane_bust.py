
from typing import Union, Iterable, Dict

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId

from .hatch_first import HatchFirst

class BaneBust(HatchFirst):
    
    def composition(self, bot) -> Dict[UnitTypeId, int]:
        composition = super().composition(bot)
        if bot.time < 5 * 60:
            composition[UnitTypeId.BANELING] = 4
            composition[UnitTypeId.ZERGLING] = 16
        return composition

    def update(self, bot):
        bot.build_spines = False
        return super().update(bot)

    def filter_upgrade(self, bot, upgrade) -> bool:
        if bot.time < 5 * 60 and upgrade == UpgradeId.CENTRIFICALHOOKS:
            return False
        return super().filter_upgrade(bot, upgrade)