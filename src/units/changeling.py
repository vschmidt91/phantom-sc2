
from __future__ import annotations
from typing import Optional, TYPE_CHECKING

from sc2.unit import Unit, UnitCommand

from .unit import CommandableUnit
from ..behaviors.search import SearchBehavior

if TYPE_CHECKING:
    from ..ai_base import AIBase

class Changeling(SearchBehavior):
    
    def __init__(self, ai: AIBase, tag: int):
        super().__init__(ai, tag)

    def get_command(self) -> Optional[UnitCommand]:
        return self.search()