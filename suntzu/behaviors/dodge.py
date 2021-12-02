
from datetime import time
from typing import Optional, Union, List, Iterable
from abc import ABC, abstractproperty
from numpy.lib.arraysetops import isin

from s2clientprotocol.data_pb2 import AbilityData
from s2clientprotocol.raw_pb2 import Effect

from sc2.position import Point2
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.ids.effect_id import EffectId
from sc2.unit import Unit
from sc2.game_state import EffectData
from sc2.unit_command import UnitCommand

from .behavior import Behavior, BehaviorResult

class DodgeElement(ABC):

    def __init__(self, positions: Iterable[Point2], radius: float):
        self.positions: List[Point2] = list(positions)
        self.radius: float = radius

class DodgeUnit(DodgeElement):

    RADIUS = {
        UnitTypeId.DISRUPTORPHASED: 1.5,
        UnitTypeId.BANELING: 2.2,
    }

    def __init__(self, unit: Unit):
        radius = self.RADIUS.get(unit.type_id, unit.radius)
        super().__init__([unit.position], radius)

class DodgeEffect(DodgeElement):

    def __init__(self, effect: EffectData):
        super().__init__(effect.positions, effect.radius)

class DodgeEffectDelayed(DodgeElement):

    RADIUS = {
        EffectId.RAVAGERCORROSIVEBILECP: 0.5,
        EffectId.NUKEPERSISTENT: 8,
    }

    DELAY = {
        EffectId.RAVAGERCORROSIVEBILECP: 50 / 22.4,
        EffectId.NUKEPERSISTENT: 320 / 22.4,
    }

    def __init__(self, effect: Effect, time: float):
        self.time = time
        self.time_of_impact = time + self.DELAY[effect.id]
        super().__init__(effect.positions, self.RADIUS[effect.id])

class DodgeBehavior(Behavior):

    def __init__(self, dodge: List[DodgeElement]):
        self.dodge: List[DodgeElement] = dodge
        self.safety_distance: float = 1

    def execute(self, unit: Unit) -> BehaviorResult:
        movement_speed = unit.movement_speed
        for dodge in self.dodge:
            if isinstance(dodge, DodgeEffectDelayed):
                time_to_impact = max(0, dodge.time_of_impact - unit._bot_object.time)
            else:
                time_to_impact = 0
            dodge_radius = unit.radius + self.safety_distance + dodge.radius - time_to_impact * movement_speed
            if dodge_radius <= 0:
                continue
            for position in dodge.positions:
                dodge_distance = unit.position.distance_to(position) - dodge_radius
                if dodge_distance < 0:
                    target = unit.position.towards(position, dodge_distance)
                    if unit.is_burrowed:
                        unit(AbilityId.BURROWUP)
                        unit.move(target, queue=True)
                    else:
                        unit.move(target)
                    return BehaviorResult.ONGOING
        return BehaviorResult.FAILURE