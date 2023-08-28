from __future__ import annotations

import math
from typing import Optional

from sc2.unit_command import UnitCommand

from ..units.unit import AIUnit, Behavior


class SurviveBehavior(Behavior):
    def __init__(self, unit: AIUnit):
        super().__init__(unit)
        self.last_damage_taken: float = -math.inf
        self.last_shield_health_percentage: float = 0.0

    def survive(self) -> Optional[UnitCommand]:
        shield_health_percentage = self.unit.state.shield_health_percentage
        if shield_health_percentage < self.last_shield_health_percentage:
            self.last_damage_taken = self.ai.time
        self.last_shield_health_percentage = shield_health_percentage

        if self.ai.time < self.last_damage_taken + 5.0:
            return self.unit.state.move(self.ai.start_location)

        return None
