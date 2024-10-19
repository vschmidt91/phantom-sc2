from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

import numpy as np
from sc2.game_state import EffectData
from sc2.ids.ability_id import AbilityId
from sc2.ids.effect_id import EffectId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.unit_command import UnitCommand

from ..units.unit import AIUnit
from .module import AIModule

if TYPE_CHECKING:
    from ..ai_base import PhantomBot

DODGE_DELAYED_EFFECTS = {
    EffectId.RAVAGERCORROSIVEBILECP,
    EffectId.NUKEPERSISTENT,
}

DODGE_EFFECTS = {
    EffectId.LURKERMP,
    EffectId.PSISTORMPERSISTENT,
}

DODGE_UNITS = {
    UnitTypeId.DISRUPTORPHASED,
    UnitTypeId.BANELING,
}


@dataclass
class DamageCircle:
    radius: float
    damage: float


class DodgeModule(AIModule):
    def __init__(self, ai: PhantomBot) -> None:
        super().__init__(ai)
        self.elements: list[DodgeElement] = list()
        self.elements_delayed: list[DodgeEffectDelayed] = list()

    async def on_step(self):

        elements_delayed_old = self.elements_delayed
        delayed_positions = {e.position for e in elements_delayed_old}

        self.elements_delayed = []
        self.elements_delayed.extend(
            element for element in elements_delayed_old if self.ai.time <= element.time_of_impact
        )
        self.elements_delayed.extend(
            DodgeEffectDelayed(effect, self.ai.time)
            for effect in self.ai.state.effects
            if (effect.id in DODGE_DELAYED_EFFECTS and next(iter(effect.positions)) not in delayed_positions)
        )

        self.elements = []
        self.elements.extend(self.elements_delayed)
        self.elements.extend(
            DodgeUnit(enemy) for enemy in self.ai.all_enemy_units if enemy and enemy.type_id in DODGE_UNITS
        )
        self.elements.extend(DodgeEffect(effect) for effect in self.ai.state.effects if effect.id in DODGE_EFFECTS)


class DodgeElement(ABC):
    def __init__(self, position: Point2, circles: list[DamageCircle]):
        self.position: Point2 = position
        self.circles: list[DamageCircle] = circles


class DodgeUnit(DodgeElement):
    CIRCLES: dict[UnitTypeId, list[DamageCircle]] = {
        UnitTypeId.DISRUPTORPHASED: [DamageCircle(1.5, 145.0)],
        UnitTypeId.BANELING: [DamageCircle(2.2, 19.0)],
    }

    def __init__(self, unit: Unit):
        position = unit.position
        circles = self.CIRCLES[unit.type_id]
        super().__init__(position, circles)


class DodgeEffect(DodgeElement):
    CIRCLES: dict[EffectId, list[DamageCircle]] = {
        EffectId.LURKERMP: [DamageCircle(0.5, 20.0)],
        EffectId.PSISTORMPERSISTENT: [DamageCircle(1.5, 80.0)],
        EffectId.RAVAGERCORROSIVEBILECP: [DamageCircle(1.0, 60)],
        EffectId.NUKEPERSISTENT: [DamageCircle(4, 150), DamageCircle(6, 75), DamageCircle(8, 75)],
    }

    def __init__(self, effect: EffectData):
        position = next(iter(effect.positions))
        circles = self.CIRCLES[effect.id]
        super().__init__(position, circles)


class DodgeEffectDelayed(DodgeEffect):
    DELAY: dict[EffectId, float] = {
        EffectId.RAVAGERCORROSIVEBILECP: 50 / 22.4,
        EffectId.NUKEPERSISTENT: 320 / 22.4,
    }

    def __init__(self, effect: EffectData, time: float):
        self.time_of_impact: float = time + self.DELAY[effect.id]
        super().__init__(effect)


class DodgeBehavior(AIUnit):
    def __init__(self, ai: PhantomBot, unit: Unit):
        super().__init__(ai, unit)
        self.safety_distance: float = 1.0

    def dodge(self) -> Optional[UnitCommand]:
        for dodge in self.ai.dodge.elements:
            distance_bonus = 0.0
            if isinstance(dodge, DodgeEffectDelayed):
                delay = (2 * self.ai.client.game_step) / 22.4
                time_remaining = max(0.0, dodge.time_of_impact - self.ai.time - delay)
                distance_bonus = 1.4 * self.unit.movement_speed * time_remaining
            distance_have = self.unit.distance_to(dodge.position)
            for circle in dodge.circles:
                distance_want = circle.radius + self.unit.radius
                if distance_have + distance_bonus < distance_want + self.safety_distance:
                    random_offset = Point2(np.random.normal(loc=0.0, scale=0.001, size=2))
                    dodge_from = dodge.position
                    if dodge_from == self.unit.position:
                        dodge_from += random_offset
                    target = dodge_from.towards(self.unit, distance_want + 2 * self.safety_distance)
                    if self.unit.is_burrowed and not self.ai.can_move(self.unit):
                        return self.unit(AbilityId.BURROWUP)
                    else:
                        return self.unit.move(target)

        return None
