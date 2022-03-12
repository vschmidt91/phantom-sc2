
from typing import Union, Iterable, Dict

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId

from ..macro_plan import MacroPlan
from .zerg_macro import ZergMacro
from .zerg_strategy import ZergStrategy

class RoachLingBust(ZergMacro):

    def build_order(self) -> Iterable:
        return [
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.EXTRACTOR,
            UnitTypeId.DRONE,
            UnitTypeId.OVERLORD,
            UnitTypeId.SPAWNINGPOOL,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            # UnitTypeId.EXTRACTOR,
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
            UpgradeId.ZERGLINGMOVEMENTSPEED,
            UnitTypeId.OVERLORD,

            UnitTypeId.ROACH,
            UnitTypeId.ROACH,
            UnitTypeId.ROACH,
            UnitTypeId.ROACH,
            UnitTypeId.ROACH,
            # UnitTypeId.ROACH,
            # UnitTypeId.ROACH,

            # UnitTypeId.OVERLORD,
            # UnitTypeId.ZERGLING,
            # UnitTypeId.ZERGLING,
            # UnitTypeId.ZERGLING,
            # UnitTypeId.ZERGLING,
            # UnitTypeId.ZERGLING,
            # UnitTypeId.ZERGLING,
            # UnitTypeId.ZERGLING,
            # UnitTypeId.ZERGLING,
            # UnitTypeId.ZERGLING,

        ]
    def update(self, bot):
        bot.build_spines = False
        # if (
        #     bot.count(UnitTypeId.SPAWNINGPOOL, include_planned=False) < 1
        #     and bot.supply_used == 14
        #     and bot.count(UnitTypeId.EXTRACTOR, include_planned=False) == 0
        # ):
        #     bot.extractor_trick_enabled = True
        bot.scout_manager.scout_enemy_natural = False
        return super().update(bot)