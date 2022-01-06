
from typing import Union, Iterable, Dict

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId

from ..macro_plan import MacroPlan
from .zerg_macro import ZergMacro
from .zerg_strategy import ZergStrategy

class RoachRush(ZergMacro):

    def build_order(self) -> Iterable:
        return [
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.OVERLORD,
            UnitTypeId.SPAWNINGPOOL,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.EXTRACTOR,
            MacroPlan(UnitTypeId.HATCHERY, max_distance=0),
            UnitTypeId.QUEEN,
            UnitTypeId.DRONE,
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
            # UnitTypeId.OVERLORD,
            # UnitTypeId.OVERLORD,
            # UnitTypeId.RAVAGER,
            # UnitTypeId.RAVAGER,
            # UnitTypeId.RAVAGER,
        ]

    # def filter_upgrade(self, bot, upgrade) -> bool:
    #     if bot.time < 3.5 * 60:
    #         return False
    #     else:
    #         return super().filter_upgrade(bot, upgrade)
        
    # def composition(self, bot) -> Dict[UnitTypeId, int]:
    #     composition = super().composition(bot)
    #     if bot.time < 4 * 60:
    #         composition[UnitTypeId.QUEEN] = min(composition[UnitTypeId.QUEEN], bot.townhalls.ready.amount)
    #     composition[UnitTypeId.RAVAGER] = 2
    #     return composition

    def update(self, bot):
        bot.scout_manager.scout_enemy_natural = False
        # if bot.supply_used == 14 and bot.count(UnitTypeId.SPAWNINGPOOL, include_planned=False) < 1 and bot.count(UnitTypeId.EXTRACTOR, include_planned=False) < 1:
        #     bot.extractor_trick_enabled = True
        return super().update(bot)