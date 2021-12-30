
from typing import Union, Iterable, Dict

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId

from .zerg_macro import ZergMacro
from .zerg_strategy import ZergStrategy

class RoachRush(ZergMacro):

    def build_order(self) -> Iterable[Union[UnitTypeId, UpgradeId]]:
        return [
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.EXTRACTOR,
            UnitTypeId.OVERLORD,
            UnitTypeId.SPAWNINGPOOL,
            # UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.EXTRACTOR,
            UnitTypeId.HATCHERY,
            UnitTypeId.QUEEN,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.ROACHWARREN,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.OVERLORD,
            UnitTypeId.ROACH,
            UnitTypeId.ROACH,
            UnitTypeId.ROACH,
            UnitTypeId.ROACH,
            UnitTypeId.ROACH,
            UnitTypeId.ROACH,
            UnitTypeId.ROACH,
            UnitTypeId.RAVAGER,
            UnitTypeId.RAVAGER,
        ]

    def filter_upgrade(self, bot, upgrade) -> bool:
        if bot.time < 3.5 * 60:
            return False
        else:
            return super().filter_upgrade(bot, upgrade)
        
    def composition(self, bot) -> Dict[UnitTypeId, int]:
        return super().composition(bot)

    def update(self, bot):
        if bot.supply_used == 14 and bot.count(UnitTypeId.SPAWNINGPOOL, include_planned=False) < 1:
            bot.extractor_trick_enabled = True
        # if bot.supply_used == 35:
        #     bot.extractor_trick_enabled = True
        return super().update(bot)