from __future__ import annotations

import math

from typing import Optional, TYPE_CHECKING

from sc2.unit_command import UnitCommand
from sc2.unit import Unit

from ..units.unit import AIUnit
from ..constants import *
from ..utils import *

if TYPE_CHECKING:
    from ..ai_base import AIBase


class SurviveBehavior(AIUnit):

    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)
        self.last_damage_taken: float = -math.inf
        self.last_shield_health_percentage: float = 0.0

    def survive(self) -> Optional[UnitCommand]:

        shield_health_percentage = self.unit.shield_health_percentage
        if shield_health_percentage < self.last_shield_health_percentage:
            self.last_damage_taken = self.ai.time
        self.last_shield_health_percentage = shield_health_percentage

        if self.ai.time < self.last_damage_taken + 5.0:
            return self.unit.move(self.ai.start_location)

        return None

