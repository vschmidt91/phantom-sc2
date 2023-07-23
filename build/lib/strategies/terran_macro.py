from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from sc2.ids.unit_typeid import UnitTypeId

from ..modules.macro import MacroId
from .strategy import Strategy

if TYPE_CHECKING:
    from ..ai_base import AIBase


class TerranMacro(Strategy):
    def __init__(self, ai: AIBase):
        super().__init__(ai)

    def build_order(self) -> Iterable[MacroId]:
        return [
            UnitTypeId.SCV,
            UnitTypeId.SCV,
            UnitTypeId.SUPPLYDEPOT,
            UnitTypeId.SCV,
            UnitTypeId.SCV,
            UnitTypeId.BARRACKS,
            UnitTypeId.REFINERY,
            UnitTypeId.SCV,
            UnitTypeId.SCV,
        ]
