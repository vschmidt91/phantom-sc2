from __future__ import annotations
from typing import TYPE_CHECKING, Iterable

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId

from .zerg_macro import ZergMacro

if TYPE_CHECKING:
    from ..ai_base import AIBase

class HatchFirst(ZergMacro):

    def __init__(self, ai: AIBase):
        super().__init__(ai)

    def build_order(self) -> Iterable:
        return [
            UnitTypeId.DRONE,
            UnitTypeId.OVERLORD,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.HATCHERY,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.EXTRACTOR,
            UnitTypeId.DRONE,
            UnitTypeId.SPAWNINGPOOL,
        ]