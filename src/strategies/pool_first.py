from __future__ import annotations
from typing import TYPE_CHECKING, Iterable

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId

from .zerg_macro import ZergMacro

if TYPE_CHECKING:
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
            UnitTypeId.HATCHERY,
            UnitTypeId.DRONE,
            UnitTypeId.EXTRACTOR,
            UnitTypeId.DRONE,
            UnitTypeId.QUEEN,
            UnitTypeId.DRONE,
            UnitTypeId.ROACHWARREN,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.OVERLORD,
            UnitTypeId.QUEEN,
            UnitTypeId.ROACH,
            UnitTypeId.ROACH,
            UnitTypeId.ROACH,
            UnitTypeId.ROACH,
        ]
        # return [
        #     UnitTypeId.DRONE,
        #     UnitTypeId.DRONE,
        #     UnitTypeId.OVERLORD,
        #     UnitTypeId.SPAWNINGPOOL,
        #     UnitTypeId.DRONE,
        #     UnitTypeId.DRONE,
        #     UnitTypeId.DRONE,
        #     UnitTypeId.HATCHERY,
        #     UnitTypeId.DRONE,
        #     UnitTypeId.DRONE,
        #     UnitTypeId.EXTRACTOR,
        #     UnitTypeId.QUEEN,
        # ]

    # async def on_step(self) -> None:
    #     await super().on_step()
    #     if self.ai.time < 220:
    #         self.ai.macro.composition.pop(UnitTypeId.RAVAGER, 0)

    # def filter_upgrade(self, upgrade) -> bool:
    #     if self.ai.time < 220:
    #         return False
    #     else:
    #         return super().filter_upgrade(upgrade)