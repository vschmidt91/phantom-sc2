from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from sc2.unit_command import UnitCommand

from ..units.unit import CommandableUnit
from ..utils import *

if TYPE_CHECKING:
    from ..ai_base import AIBase


class CancelBehavior(CommandableUnit):

    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)

    def cancel(self) -> Optional[UnitCommand]:
        if self.unit.is_ready:
            return None
