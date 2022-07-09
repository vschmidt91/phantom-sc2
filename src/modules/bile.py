from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sc2.unit_command import UnitCommand

from ..units.unit import CommandableUnit
from .module import AIModule
from ..constants import *
from ..utils import *

if TYPE_CHECKING:
    from ..ai_base import AIBase

BILE_ABILITY = AbilityId.EFFECT_CORROSIVEBILE


class BileModule(AIModule):

    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)
        self.enemy_positions: Dict[int, Point2] = dict()
        self.time: float = 0.0

    async def on_step(self):
        self.enemy_positions = {
            enemy.unit.tag: enemy.unit.position
            for enemy in self.ai.unit_manager.enemies.values()
            if enemy.unit
        }
        self.time = self.ai.time

    def estimate_enemy_velocity(self, unit: Unit) -> Point2:
        previous_position = self.enemy_positions.get(unit.tag) or unit.position
        dt = self.ai.time - self.time
        if 0 < dt:
            dx = unit.position - previous_position
            return dx / dt
        return Point2((0, 0))


class BileBehavior(CommandableUnit):

    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)
        self.last_used = 0

    def bile_priority(self, target: Unit):
        if not self.ai.is_visible(target.position):
            return 0
        if not self.unit.in_ability_cast_range(BILE_ABILITY, target.position):
            return 0
        if target.is_hallucination:
            return 0
        if target.type_id in CHANGELINGS:
            return 0
        priority = 10 + max(target.ground_dps, target.air_dps)
        priority /= 100 + target.health + target.shield
        priority /= 2 + target.movement_speed
        return priority

    def bile(self) -> Optional[UnitCommand]:

        if self.unit.type_id != UnitTypeId.RAVAGER:
            return None

        if self.ai.state.game_loop < self.last_used + self.ai.techtree.abilities[
            AbilityId.EFFECT_CORROSIVEBILE].cooldown:
            return None

        targets = (
            target.unit
            for target in self.ai.enumerate_enemies()
            if target.unit
        )
        target: Unit = max(
            targets,
            key=lambda t: self.bile_priority(t),
            default=None
        )
        if not target:
            return None
        if self.bile_priority(target) <= 0:
            return None
        velocity = self.ai.biles.estimate_enemy_velocity(target)
        if 2 < velocity.length:
            velocity = Point2((0, 0))
        predicted_position = target.position + velocity * 50 / 22.4
        self.last_used = self.ai.state.game_loop
        return self.unit(BILE_ABILITY, target=predicted_position)
