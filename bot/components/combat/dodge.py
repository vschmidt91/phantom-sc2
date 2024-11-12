from dataclasses import dataclass

import numpy as np
from sc2.ids.ability_id import AbilityId
from sc2.ids.effect_id import EffectId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from bot.common.action import Action, Move, UseAbility
from bot.common.base import BotBase


@dataclass(frozen=True)
class DodgeCircle:
    radius: float
    damage: float


DODGE_UNITS = {
    UnitTypeId.DISRUPTORPHASED: [DodgeCircle(1.5, 145.0)],
    UnitTypeId.BANELING: [DodgeCircle(2.2, 19.0)],
}

DODGE_EFFECTS = {
    EffectId.LURKERMP: [DodgeCircle(0.5, 20.0)],
    EffectId.PSISTORMPERSISTENT: [DodgeCircle(1.5, 80.0)],
    EffectId.RAVAGERCORROSIVEBILECP: [DodgeCircle(1.0, 60)],
    EffectId.NUKEPERSISTENT: [DodgeCircle(4, 150), DodgeCircle(6, 75), DodgeCircle(8, 75)],
}

EFFECT_DELAY: dict[EffectId, float] = {
    EffectId.RAVAGERCORROSIVEBILECP: 50 / 22.4,
    EffectId.NUKEPERSISTENT: 320 / 22.4,
}


@dataclass(frozen=True)
class DodgeItem:
    position: Point2
    circle: DodgeCircle


@dataclass(frozen=True)
class DodgeResult:

    context: BotBase
    items: dict[DodgeItem, float]
    safety_distance: float = 1.0
    safety_time = 0.1
    min_distance = 1e-3

    def dodge_with(self, unit: Unit) -> Action | None:
        for item, time_of_impact in self.items.items():
            if action := self._dodge_item(unit, item, time_of_impact):
                return action
        return None

    def _dodge_item(self, unit: Unit, item: DodgeItem, time_of_impact: float) -> Action | None:
        time_remaining = max(0.0, time_of_impact - self.context.time - self.safety_time)
        distance_bonus = 1.4 * unit.movement_speed * time_remaining
        distance_have = unit.distance_to(item.position)
        distance_want = item.circle.radius + unit.radius
        if distance_have + distance_bonus >= distance_want + self.safety_distance:
            return None
        if unit.is_burrowed and not self.context.can_move(unit):
            return UseAbility(unit, AbilityId.BURROWUP)
        dodge_from = item.position
        if distance_have < self.min_distance:
            dodge_from += Point2(np.random.normal(loc=0.0, scale=self.min_distance, size=2))
        target = dodge_from.towards(unit, distance_want + self.safety_distance)
        return Move(unit, target)


class Dodge:

    _effects: dict[DodgeItem, float] = {}

    def update(self, context: BotBase) -> DodgeResult:

        units = {
            DodgeItem(unit.position, circle): context.time
            for unit in context.all_enemy_units
            for circle in DODGE_UNITS.get(unit.type_id, [])
        }

        active_effects: set[DodgeItem] = set()
        for effect in context.state.effects:
            time_of_impact = context.time + EFFECT_DELAY.get(effect.id, 0.0)
            for position in effect.positions:
                for circle in DODGE_EFFECTS.get(effect.id, []):
                    item = DodgeItem(position, circle)
                    active_effects.add(item)
                    self._effects.setdefault(item, time_of_impact)

        # remove old effects that impacted
        for item, time_of_impact in list(self._effects.items()):
            if item not in active_effects and time_of_impact < context.time:
                del self._effects[item]

        return DodgeResult(context, units | self._effects)
