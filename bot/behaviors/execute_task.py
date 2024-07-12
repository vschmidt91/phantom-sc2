from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sc2.unit import UnitCommand
from sc2.unit import Unit

from ..units.unit import AIUnit
from ..tasks.task import Task

if TYPE_CHECKING:
    from ..ai_base import AIBase


class ExecuteTaskBehavior(AIUnit):

    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)
        self.task: Optional[Task] = None
        
    def get_command(self) -> Optional[UnitCommand]:
        if self.task:
            return self.task.get_command(self)
        return super().get_command()