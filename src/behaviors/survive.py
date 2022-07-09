from __future__ import annotations

import math

from typing import Optional, TYPE_CHECKING

from sc2.unit_command import UnitCommand
from sc2.unit import Unit

from ..units.unit import CommandableUnit
from ..constants import *
from ..utils import *

if TYPE_CHECKING:
    from ..ai_base import AIBase


class SurviveBehavior(CommandableUnit):

    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)
        self.last_damage_taken: float = -math.inf

    def survive(self) -> Optional[UnitCommand]:

        if self.ai.time < self.last_damage_taken + 5:
            return self.unit.move(self.ai.start_location)

        return None

