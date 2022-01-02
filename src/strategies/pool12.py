
from typing import Union, Iterable, Dict

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId

from .zerg_macro import ZergMacro
from .zerg_strategy import ZergStrategy
from ..macro_plan import MacroPlan

class Pool12(ZergMacro):

    def build_order(self) -> Iterable[Union[UnitTypeId, UpgradeId]]:
        return [
            UnitTypeId.SPAWNINGPOOL,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.OVERLORD,
            UnitTypeId.ZERGLING,
            UnitTypeId.ZERGLING,
            UnitTypeId.ZERGLING,
            UnitTypeId.HATCHERY,
            UnitTypeId.ZERGLING,
            UnitTypeId.ZERGLING,
            # UnitTypeId.QUEEN,
            # UnitTypeId.DRONE,
            # UnitTypeId.OVERLORD,
        ]

    def update(self, bot):
        if 2.5 * 60 < bot.time and not bot.count(UpgradeId.ZERGLINGMOVEMENTSPEED):
            bot.add_macro_plan(MacroPlan(UpgradeId.ZERGLINGMOVEMENTSPEED))