
from __future__ import annotations
from typing import Optional, TYPE_CHECKING

from sc2.unit import Unit, UnitCommand
from src.units.unit import AIUnit

from ..behaviors.behavior import Behavior
from ..modules.dodge import DodgeBehavior
from ..modules.macro import MacroBehavior
from ..behaviors.gather import GatherBehavior

if TYPE_CHECKING:
    from ..ai_base import AIBase

class Worker(DodgeBehavior, MacroBehavior, GatherBehavior):
    
    def __init__(self, ai: AIBase, tag: int):
        super().__init__(ai, tag)

    def get_command(self) -> Optional[UnitCommand]:
        return self.dodge() or self.macro() or self.gather()