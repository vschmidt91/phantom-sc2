
from typing import Union, Iterable, Dict

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId

from ..macro_plan import MacroPlan
from .zerg_macro import ZergMacro
from .zerg_strategy import ZergStrategy
from ..ai_base import AIBase

class HatchFirst(ZergMacro):

    def __init__(self, ai: AIBase):
        super().__init__(ai)

    def build_order(self) -> Iterable:
        return [

            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
            # UnitTypeId.EXTRACTOR,
            # MacroPlan(UnitTypeId.HATCHERY, max_distance=0),
            # UnitTypeId.DRONE,
            # UnitTypeId.EXTRACTOR,
            # UnitTypeId.OVERLORD,
            # UnitTypeId.SPAWNINGPOOL,


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
            UnitTypeId.DRONE,
            UnitTypeId.SPAWNINGPOOL,
            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
            # UnitTypeId.OVERLORD,
            # UnitTypeId.QUEEN,
            # UnitTypeId.QUEEN,
            # UnitTypeId.ZERGLING,

        ]

    def filter_upgrade(self, upgrade) -> bool:
        if self.ai.time < 2 * 60:
            return False
        return super().filter_upgrade(self.ai, upgrade)

    def update(self):
        if (
            self.ai.supply_used == 14
            and self.ai.count(UnitTypeId.EXTRACTOR, include_planned=False) < 1
            # and self.ai.townhalls.amount < 2
            and self.ai.count(UnitTypeId.OVERLORD, include_planned=False) < 2
        ):
            self.ai.extractor_trick_enabled = True
        # if 160 < self.ai.time and self.ai.count(UpgradeId.OVERLORDSPEED) < 1:
        #     self.ai.add_macro_plan(MacroPlan(UpgradeId.OVERLORDSPEED))
        return super().update()