from __future__ import annotations
from typing import TYPE_CHECKING, Optional
import logging
from abc import ABC, abstractmethod

from sc2.unit import Unit, UnitCommand

from ..ai_component import AIComponent

if TYPE_CHECKING:
    from ..ai_base import AIBase

class AIUnit(ABC, AIComponent):
    
    def __init__(self, ai: AIBase, tag: int):
        super().__init__(ai)
        # clss = list(self.__class__.__mro__)
        # for cls in clss:
        #     if issubclass(AIUnit, cls):
        #         continue
        #     super(cls, self).__init__(ai, tag)
        self.tag = tag
        self.unit: Unit = None

    def __hash__(self) -> int:
        return hash(self.tag)
        
    def on_step(self) -> None:
        self.unit = self.ai.unit_by_tag.get(self.tag)
        if self.unit:
            if command := self.get_command():
                if not any(self.unit.orders) or not self.ai.order_matches_command(self.unit.orders[0], command):
                    if not self.ai.do(command, subtract_cost=False, subtract_supply=False):
                        logging.error(f"command failed: {command}")

    @abstractmethod
    def get_command(self) -> Optional[UnitCommand]:
        raise NotImplementedError()