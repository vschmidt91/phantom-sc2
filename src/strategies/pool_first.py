
from typing import Union, Iterable, Dict

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId

from ..modules.macro import MacroPlan
from .zerg_macro import ZergMacro
from .zerg_strategy import ZergStrategy
from ..ai_base import AIBase

class PoolFirst(ZergMacro):

    def __init__(self, ai: AIBase):
        super().__init__(ai)

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
            MacroPlan(UnitTypeId.HATCHERY, max_distance=0),
            UnitTypeId.QUEEN,
            UnitTypeId.ZERGLING,
            UnitTypeId.ZERGLING,
        ]

    def update(self) -> None:
        # if (
        #     self.ai.supply_used == 14
        #     and self.ai.count(UnitTypeId.EXTRACTOR, include_planned=False) < 1
        # ):
        #     self.ai.extractor_trick_enabled = True
        return super().update()