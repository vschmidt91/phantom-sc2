from __future__ import annotations

from dataclasses import dataclass
from itertools import chain
from typing import TYPE_CHECKING

from sc2.ids.ability_id import AbilityId
from sc2.ids.effect_id import EffectId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from phantom.common.action import Action, Move, UseAbility
from phantom.common.utils import RNG

if TYPE_CHECKING:
    from phantom.main import PhantomBot
    from phantom.observation import Observation


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
    EffectId.PSISTORMPERSISTENT: [DodgeCircle(1.5, 96.0)],
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


class Dodge:
    def __init__(self, bot: PhantomBot) -> None:
        self.bot = bot
        self.dodge_effects = dict[DodgeItem, float]()
        self.dodge_units = dict[DodgeItem, float]()
        self.safety_distance = 1.5
        self.safety_time = 0.5
        self.min_distance = 1e-3
        self._units = list[Unit]()

    def on_step(self, observation: Observation | None = None) -> None:
        self._units = list(observation.bot.units) if observation is not None else list(self.bot.units)
        self.dodge_units = {
            DodgeItem(unit.position, circle): self.bot.time
            for unit in self.bot.enemy_units(set(DODGE_UNITS))
            for circle in DODGE_UNITS[unit.type_id]
        }

        # add new effects
        for effect in self.bot.state.effects:
            # this assumes the ability was witnessed being cast, which could be false
            time_of_impact = self.bot.time + EFFECT_DELAY.get(effect.id, 0.0)
            for position in effect.positions:
                for circle in DODGE_EFFECTS.get(effect.id, []):
                    item = DodgeItem(position, circle)
                    self.dodge_effects.setdefault(item, time_of_impact)

        # remove old effects that impacted
        for item, time_of_impact in list(self.dodge_effects.items()):
            if time_of_impact < self.bot.time:
                del self.dodge_effects[item]

    def units_to_dodge_with(self) -> list[Unit]:
        return self._units

    def get_action(self, unit: Unit) -> Action | None:
        return self.dodge_with(unit)

    def dodge_with(self, unit: Unit) -> Action | None:
        for item, time_of_impact in chain(self.dodge_effects.items(), self.dodge_units.items()):
            if action := self._dodge_item(unit, item, time_of_impact):
                return action
        return None

    def _dodge_item(self, unit: Unit, item: DodgeItem, time_of_impact: float) -> Action | None:
        time_remaining = max(0.0, time_of_impact - self.bot.time - self.safety_time)
        distance_bonus = 1.4 * unit.movement_speed * time_remaining
        distance_have = unit.distance_to(item.position)
        distance_want = item.circle.radius + unit.radius
        if distance_have + distance_bonus >= distance_want + self.safety_distance:
            return None
        if unit.is_burrowed and not self.bot.can_move(unit):
            return UseAbility(AbilityId.BURROWUP)
        dodge_from = item.position
        if distance_have < self.min_distance:
            # random offset in case the effect is exactly on top of the unit
            dodge_from += Point2(RNG.normal(loc=0.0, scale=self.min_distance, size=2))
        target = dodge_from.towards(unit, distance_want + self.safety_distance)
        return Move(target)
