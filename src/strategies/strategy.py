
from __future__ import annotations
from abc import ABC, abstractproperty
import math
from typing import Union, Iterable, Dict, TYPE_CHECKING

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId
from ..modules.macro import MacroPlan, MacroId

from ..modules.module import AIModule
if TYPE_CHECKING:
    from ..ai_base import AIBase

class Strategy(ABC, AIModule):

    def __init__(self, ai: AIBase):
        super().__init__(ai)
        for step in self.build_order():
            plan = MacroPlan(step)
            plan.priority = math.inf
            self.ai.macro.add_plan(plan)

    @abstractproperty
    def build_order(self) -> Iterable[MacroId]:
        raise NotImplementedError

    def filter_upgrade(self, upgrade: UpgradeId) -> bool:
        return True
        
    @property
    def name(self) -> str:
        return type(self).__name__