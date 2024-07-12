from __future__ import annotations

import math
from typing import Counter, TYPE_CHECKING, Iterable

import numpy as np
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from .strategy import Strategy
from ..modules.macro import MacroId

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