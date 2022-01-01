
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
            # UnitTypeId.EXTRACTOR,
            UnitTypeId.OVERLORD,
            UnitTypeId.SPAWNINGPOOL,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.EXTRACTOR,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.HATCHERY,
            UnitTypeId.QUEEN,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.ROACHWARREN,
            UnitTypeId.DRONE,
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
            # UnitTypeId.ROACH,
            UnitTypeId.OVERLORD,
            UnitTypeId.RAVAGER,
            UnitTypeId.RAVAGER,
            # UnitTypeId.RAVAGER,
        ]

    # def filter_upgrade(self, bot, upgrade) -> bool:
    #     if bot.time < 3.5 * 60:
    #         return False
    #     else:
    #         return super().filter_upgrade(bot, upgrade)
        
    # def composition(self, bot) -> Dict[UnitTypeId, int]:
    #     if bot.time < 4 * 60:
    #         return { UnitTypeId.QUEEN: 2, UnitTypeId.DRONE: 32, UnitTypeId.ZERGLING: 0 }
    #     else:
    #         return super().composition(bot)

    def update(self, bot):
        bot.strict_macro = bot.time < 3 * 60
        bot.scout_manager.scout_enemy_natural = False
        if bot.supply_used == 14 and bot.count(UnitTypeId.SPAWNINGPOOL, include_planned=False) < 1:
            bot.extractor_trick_enabled = True
        # elif bot.supply_used == 35 and 7 <= bot.count(UnitTypeId.ROACH, include_planned=False):
        #     bot.extractor_trick_enabled = True
        else:
            bot.extractor_trick_enabled = False
        return super().update(bot)