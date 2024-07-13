from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

import numpy as np
from sc2.unit import AbilityId, Point2, Unit, UnitCommand, UnitTypeId

from ..constants import CHANGELINGS, COOLDOWN
from ..modules.module import AIModule
from ..units.unit import AIUnit

if TYPE_CHECKING:
    from ..ai_base import AIBase

BILE_ABILITY = AbilityId.EFFECT_CORROSIVEBILE


class BileBehavior(AIUnit):
    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)
        self.last_used = 0

    def bile_priority(self, target: Unit) -> float:
        if not target.is_enemy:
            return 0.0
        if not self.ai.is_visible(target.position):
            return 0.0
        if not self.unit.in_ability_cast_range(BILE_ABILITY, target.position):
            return 0.0
        if target.is_hallucination:
            return 0.0
        if target.type_id in CHANGELINGS:
            return 0.0
        priority = 10.0 + max(target.ground_dps, target.air_dps)
        priority /= 100.0 + target.health + target.shield
        priority /= 2.0 + target.movement_speed
        return priority

    def bile(self) -> Optional[UnitCommand]:
        if self.unit.type_id != UnitTypeId.RAVAGER:
            return None

        if self.ai.state.game_loop < self.last_used + COOLDOWN[AbilityId.EFFECT_CORROSIVEBILE]:
            return None

        target = max(
            self.ai.unit_manager.units_in_circle(self.unit.position, 10),
            key=lambda t: self.bile_priority(t),
            default=None,
        )

        if not target:
            return None

        if self.bile_priority(target) <= 0:
            return None

        self.last_used = self.ai.state.game_loop

        return self.unit(BILE_ABILITY, target=target.position)
