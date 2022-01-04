
from typing import Union, Iterable, Dict

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId

from ..macro_plan import MacroPlan
from .zerg_macro import ZergMacro
from .zerg_strategy import ZergStrategy

class HatchFirst(ZergMacro):

    def build_order(self) -> Iterable:
        return [
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.EXTRACTOR,
            UnitTypeId.OVERLORD,
            MacroPlan(UnitTypeId.HATCHERY, max_distance=0),
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.EXTRACTOR,
            UnitTypeId.SPAWNINGPOOL,
            UpgradeId.ZERGLINGMOVEMENTSPEED,
        ]

    def update(self, bot):
        if bot.supply_used == 14 and bot.count(UnitTypeId.EXTRACTOR, include_planned=False) == 0:
            bot.extractor_trick_enabled = True
        return super().update(bot)