from __future__ import annotations

from typing import Iterable, TYPE_CHECKING

from sc2.ids.unit_typeid import UnitTypeId

from .zerg_macro import ZergMacro
from ..modules.macro import MacroId

if TYPE_CHECKING:
    from ..ai_base import AIBase


class HatchFirst(ZergMacro):

    def __init__(self, ai: AIBase):
        super().__init__(ai)

    def build_order(self) -> Iterable[MacroId]:
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
            UnitTypeId.SPAWNINGPOOL,
            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
            # UnitTypeId.HATCHERY,
        ]