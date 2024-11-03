from dataclasses import dataclass

import numpy as np
from loguru import logger
from sc2.ids.effect_id import EffectId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from ..action import Action, Move
from ..base import BotBase


@dataclass(frozen=True)
class DamageCircle:
    radius: float
    damage: float


DODGE_UNITS = {
    UnitTypeId.DISRUPTORPHASED: [DamageCircle(1.5, 145.0)],
    UnitTypeId.BANELING: [DamageCircle(2.2, 19.0)],
}

DODGE_EFFECTS = {
    EffectId.LURKERMP: [DamageCircle(0.5, 20.0)],
    EffectId.PSISTORMPERSISTENT: [DamageCircle(1.5, 80.0)],
    EffectId.RAVAGERCORROSIVEBILECP: [DamageCircle(1.0, 60)],
    EffectId.NUKEPERSISTENT: [DamageCircle(4, 150), DamageCircle(6, 75), DamageCircle(8, 75)],
}

EFFECT_DELAY: dict[EffectId, float] = {
    EffectId.RAVAGERCORROSIVEBILECP: 50 / 22.4,
    EffectId.NUKEPERSISTENT: 320 / 22.4,
}


@dataclass(frozen=True)
class DodgeElement:
    position: Point2
    circle: DamageCircle


@dataclass
class DodgeResult:
    elements: dict[DodgeElement, float]
    safety_distance: float = 1.0

    def dodge_with(self, context: BotBase, unit: Unit) -> Action | None:

        for element, time_of_impact in self.elements.items():
            delay = 4 / 22.4
            time_remaining = max(0.0, time_of_impact - context.time - delay)
            distance_bonus = 1.4 * unit.movement_speed * time_remaining
            distance_have = unit.distance_to(element.position)
            distance_want = element.circle.radius + unit.radius
            if distance_have + distance_bonus < distance_want + self.safety_distance:
                random_offset = Point2(np.random.normal(loc=0.0, scale=0.001, size=2))
                dodge_from = element.position
                if dodge_from == unit.position:
                    dodge_from += random_offset
                target = dodge_from.towards(unit, distance_want + 2 * self.safety_distance)
                # if unit.is_burrowed and not self.can_move(unit):
                #     return UseAbility(unit, AbilityId.BURROWUP)
                # else:
                return Move(unit, target)
        return None


class Dodge:

    _effects: dict[DodgeElement, float] = {}

    def update_dodge(self, context: BotBase) -> DodgeResult:

        units = {
            DodgeElement(unit.position, circle): context.time
            for unit in context.all_enemy_units
            for circle in DODGE_UNITS.get(unit.type_id, [])
        }

        active_effects: set[DodgeElement] = set()
        for effect in context.state.effects:
            time_of_impact = context.time + EFFECT_DELAY.get(effect.id, 0.0)
            for position in effect.positions:
                for circle in DODGE_EFFECTS.get(effect.id, []):
                    element = DodgeElement(position, circle)
                    active_effects.add(element)
                    self._effects.setdefault(element, time_of_impact)

        # remove old effects that impacted
        for element, time_of_impact in list(self._effects.items()):
            if element not in active_effects and time_of_impact < context.time:
                logger.debug(f"Removing effect: {element} @ {time_of_impact}")
                del self._effects[element]

        return DodgeResult(units | self._effects)
