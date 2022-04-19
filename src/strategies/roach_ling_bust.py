
from typing import Union, Iterable, Dict

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId
from src.constants import BUILD_ORDER_PRIORITY

from ..modules.macro import MacroPlan
from .zerg_macro import ZergMacro
from .zerg_strategy import ZergStrategy

from ..ai_base import AIBase

class RoachLingBust(ZergMacro):

    def __init__(self, ai: AIBase):
        super().__init__(ai)

    def build_order(self) -> Iterable:
        return [

            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.EXTRACTOR,
            UnitTypeId.DRONE,
            UnitTypeId.OVERLORD,
            UnitTypeId.SPAWNINGPOOL,
            UnitTypeId.DRONE,
            # UnitTypeId.EXTRACTOR,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.HATCHERY,
            UnitTypeId.QUEEN,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.ROACHWARREN,
            UnitTypeId.DRONE,
            UpgradeId.ZERGLINGMOVEMENTSPEED,
            UnitTypeId.OVERLORD,

            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
            # UnitTypeId.EXTRACTOR,
            # UnitTypeId.OVERLORD,
            # UnitTypeId.SPAWNINGPOOL,
            # UnitTypeId.EXTRACTOR,
            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
            # UnitTypeId.HATCHERY,
            # UnitTypeId.QUEEN,
            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
            # UnitTypeId.ROACHWARREN,
            # UnitTypeId.DRONE,
            # UpgradeId.ZERGLINGMOVEMENTSPEED,
            # UnitTypeId.OVERLORD,

            UnitTypeId.ROACH,
            UnitTypeId.ROACH,
            UnitTypeId.ROACH,
            UnitTypeId.ROACH,
            UnitTypeId.ROACH,
            UnitTypeId.ROACH,
            UnitTypeId.ROACH,
            
            UnitTypeId.OVERLORD,
            UnitTypeId.ZERGLING,
            UnitTypeId.ZERGLING,
            UnitTypeId.ZERGLING,
            UnitTypeId.ZERGLING,
            UnitTypeId.ZERGLING,
            UnitTypeId.ZERGLING,
            UnitTypeId.ZERGLING,
            UnitTypeId.ZERGLING,
            # UnitTypeId.ZERGLING,

            # UnitTypeId.OVERLORD,
            # UnitTypeId.ZERGLING,

        ]

    def update(self) -> None:
        self.ai.scout_manager.scout_enemy_natural = False

        if 1 <= self.ai.count(UnitTypeId.ROACHWARREN, include_planned=False, include_pending=False):
            self.ai.composition = { UnitTypeId.ZERGLING: 32 }
            
        # self.ai.max_gas = self.ai.time < 160
        # if (
        #     self.ai.supply_used == 14
        #     and self.ai.count(UnitTypeId.EXTRACTOR, include_planned=False) < 1
        #     and self.ai.count(UnitTypeId.OVERLORD, include_planned=False) < 2
        #     and self.ai.count(UnitTypeId.SPAWNINGPOOL, include_planned=False) < 1
        # ):
        #     self.ai.extractor_trick_enabled = True
        # if self.ai.count(UnitTypeId.ROACH, include_pending=False, include_actual=False) < 1:
        #     self.ai.add_macro_plan(MacroPlan(UnitTypeId.ROACH, priority=BUILD_ORDER_PRIORITY))
        # if self.ai.count(UnitTypeId.ZERGLING, include_pending=False, include_actual=False) < 1:
        #     self.ai.add_macro_plan(MacroPlan(UnitTypeId.ZERGLING, priority=BUILD_ORDER_PRIORITY))
        return super().update()