
from typing import Union, Iterable, Dict

from matplotlib.image import composite_images

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId

from .zerg_macro import ZergMacro
from .zerg_strategy import ZergStrategy
from ..macro_plan import MacroPlan

class Pool12(ZergMacro):

    def build_order(self) -> Iterable:
        return [
            UnitTypeId.SPAWNINGPOOL,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.OVERLORD,
            UnitTypeId.ZERGLING,
            UnitTypeId.ZERGLING,
            UnitTypeId.ZERGLING,
            UnitTypeId.QUEEN,
            MacroPlan(UnitTypeId.HATCHERY, max_distance=0),
            UnitTypeId.ZERGLING,
            UnitTypeId.ZERGLING,
            # UnitTypeId.OVERLORD,
            # UnitTypeId.QUEEN,
            # UnitTypeId.ZERGLING,
            # UnitTypeId.ZERGLING,
            # UnitTypeId.DRONE,
            # UnitTypeId.OVERLORD,
        ]

    def composition(self, bot) -> Dict[UnitTypeId, int]:
        composition = super().composition(bot)
        if UnitTypeId.ROACH in composition and bot.time < 2.5 * 60:
            del composition[UnitTypeId.ROACH]
        return composition

    def filter_upgrade(self, bot, upgrade) -> bool:
        if bot.time < 2.5 * 60:
            return False
        return super().filter_upgrade(bot, upgrade)

    # def update(self, bot):
    #     if 2.5 * 60 < bot.time and not bot.count(UpgradeId.ZERGLINGMOVEMENTSPEED):
    #         bot.add_macro_plan(MacroPlan(UpgradeId.ZERGLINGMOVEMENTSPEED))