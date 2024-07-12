from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from .zerg_macro import ZergMacro
from ..modules.macro import MacroId

if TYPE_CHECKING:
    from ..ai_base import AIBase


class PoolFirst(ZergMacro):

    def __init__(self, ai: AIBase):
        super().__init__(ai)

    def build_order(self) -> Iterable[MacroId]:
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
            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
            # UnitTypeId.EXTRACTOR,
            # UnitTypeId.HATCHERY,
            # UnitTypeId.QUEEN,
            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
            # UnitTypeId.ROACHWARREN,
            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
            # UnitTypeId.OVERLORD,
            # UnitTypeId.ROACH,
            # UnitTypeId.ROACH,
            # UnitTypeId.ROACH,
            # UnitTypeId.ROACH,
            # UnitTypeId.ROACH,
            # UnitTypeId.ROACH,
            # UnitTypeId.ROACH,
        ]

    def filter_upgrade(self, upgrade) -> bool:
        if upgrade == UpgradeId.ZERGLINGMOVEMENTSPEED:
            return 1 < self.ai.townhalls.amount
        else:
            return super().filter_upgrade(upgrade)