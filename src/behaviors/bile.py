from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sc2.unit import Unit, UnitCommand, UnitTypeId, AbilityId, Point2

from ..units.unit import CommandableUnit, EnemyUnit
from ..modules.module import AIModule
from ..constants import CHANGELINGS, COOLDOWN

if TYPE_CHECKING:
    from ..ai_base import AIBase

BILE_ABILITY = AbilityId.EFFECT_CORROSIVEBILE

class BileBehavior(CommandableUnit):

    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)
        self.last_used = 0

    def bile_priority(self, target: Unit) -> float:
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

        if target := max(
            self.ai.unit_manager.enemies.values(),
            key=lambda t:self.bile_priority(t.unit),
            default=None
        ):
            if self.bile_priority(target.unit) <= 0:
                return None
            velocity = target.estimated_velocity
            if 2 < velocity.length:
                velocity = Point2((0, 0))
            predicted_position = target.unit.position + velocity * 50 / 22.4
            self.last_used = self.ai.state.game_loop
            return self.unit(BILE_ABILITY, target=predicted_position)

        return None