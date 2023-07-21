from __future__ import annotations

from typing import TYPE_CHECKING, Any, Coroutine, Iterable

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from ..modules.macro import MacroId
from .zerg_macro import ZergMacro

if TYPE_CHECKING:
    from ..ai_base import AIBase


class HatchFirst(ZergMacro):
    def __init__(self, ai: AIBase):
        super().__init__(ai)

    def build_order(self) -> Iterable[MacroId]:
        return [
            # UnitTypeId.DRONE,
            # UnitTypeId.OVERLORD,
            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
            # UnitTypeId.HATCHERY,
            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
            # UnitTypeId.EXTRACTOR,
            # UnitTypeId.SPAWNINGPOOL,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.EXTRACTOR,
            UnitTypeId.DRONE,
            UnitTypeId.OVERLORD,
            UnitTypeId.HATCHERY,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.SPAWNINGPOOL,
            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
        ]

    def filter_upgrade(self, upgrade) -> bool:
        if upgrade == UpgradeId.ZERGLINGMOVEMENTSPEED:
            return 16 < self.ai.count(UnitTypeId.DRONE, include_pending=False, include_planned=False)
        return super().filter_upgrade(upgrade)

    async def on_step(self) -> Coroutine[Any, Any, None]:
        if self.ai.supply_used == 14 and any(self.ai.gas_buildings.not_ready) and not self.ai.extractor_trick_enabled:
            # print("extractor_trick_enabled")
            self.ai.extractor_trick_enabled = True
        return await super().on_step()
