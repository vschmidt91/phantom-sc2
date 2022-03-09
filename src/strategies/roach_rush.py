
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
            UnitTypeId.EXTRACTOR,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            MacroPlan(UnitTypeId.HATCHERY, max_distance=0),
            UnitTypeId.QUEEN,
            UnitTypeId.ZERGLING,
            UnitTypeId.ZERGLING,
            UnitTypeId.ROACHWARREN,
            UnitTypeId.DRONE,
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
        ]

    def filter_upgrade(self, bot, upgrade) -> bool:
        if bot.time < 160:
            return False
        return super().filter_upgrade(bot, upgrade)

    # def build_order(self) -> Iterable:
    #     return [
    #         UnitTypeId.DRONE,
    #         UnitTypeId.DRONE,
    #         UnitTypeId.OVERLORD,
    #         UnitTypeId.SPAWNINGPOOL,
    #         UnitTypeId.DRONE,
    #         UnitTypeId.DRONE,
    #         UnitTypeId.DRONE,
    #         UnitTypeId.DRONE,
    #         UnitTypeId.HATCHERY,
    #         UnitTypeId.EXTRACTOR,
    #         UnitTypeId.ZERGLING,
    #         UnitTypeId.ZERGLING,
    #         UnitTypeId.ZERGLING,
    #         # UnitTypeId.ROACHWARREN,
    #         # UnitTypeId.DRONE,
    #         # UnitTypeId.QUEEN,
    #         # UnitTypeId.OVERLORD,
    #         # UnitTypeId.ROACH,
    #         # UnitTypeId.ROACH,
    #         # UnitTypeId.ROACH,
    #         # UnitTypeId.ROACH,
    #         # UnitTypeId.ROACH,
    #     ]

    def update(self, bot):
        bot.scout_manager.scout_enemy_natural = False
        return super().update(bot)