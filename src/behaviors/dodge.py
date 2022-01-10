from __future__ import annotations
from datetime import time
from dataclasses import dataclass
from typing import Optional, Union, List, Iterable, Dict, TYPE_CHECKING
from abc import ABC, abstractmethod, abstractproperty
from numpy.lib.arraysetops import isin
from s2clientprotocol.common_pb2 import Point

from s2clientprotocol.data_pb2 import AbilityData
from s2clientprotocol.raw_pb2 import Effect

from sc2.position import Point2
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.ids.effect_id import EffectId
from sc2.unit import Unit
from sc2.game_state import EffectData
from sc2.unit_command import UnitCommand

from ..utils import *
from .behavior import Behavior, BehaviorResult, UnitBehavior
from ..ai_component import AIComponent
if TYPE_CHECKING:
    from ..ai_base import AIBase
 
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

class DodgeElement(ABC):

    def __init__(self, position: Point2, circles: List[DamageCircle]):
        self.position: Point2 = position
        self.circles: List[DamageCircle] = circles

class DodgeUnit(DodgeElement):

    CIRCLES: Dict[EffectId, List[Tuple[float, float]]] = {
        UnitTypeId.DISRUPTORPHASED: [DamageCircle(1.5, 145.0)],
        UnitTypeId.BANELING: [DamageCircle(2.2, 19.0)],
    }

    def __init__(self, unit: Unit):
        position = unit.position
        circles = self.CIRCLES[unit.type_id]
        super().__init__(position, circles)

class DodgeEffect(DodgeElement):

    CIRCLES: Dict[EffectId, List[Tuple[float, float]]] = {
        EffectId.LURKERMP: [DamageCircle(0.5, 20.0)],
        EffectId.PSISTORMPERSISTENT: [DamageCircle(1.5, 80.0)],
        EffectId.RAVAGERCORROSIVEBILECP: [DamageCircle(0.0, 60)],
        EffectId.NUKEPERSISTENT: [DamageCircle(4, 150), DamageCircle(6, 75), DamageCircle(8, 75)],
    }

    def __init__(self, effect: EffectData):
        position = next(iter(effect.positions))
        circles = self.CIRCLES[effect.id]
        super().__init__(position, circles)

class DodgeEffectDelayed(DodgeEffect):

    DELAY: Dict[EffectId, float] = {
        EffectId.RAVAGERCORROSIVEBILECP: 50 / 22.4,
        EffectId.NUKEPERSISTENT: 320 / 22.4,
    }

    def __init__(self, effect: EffectData, time: float):
        self.time_of_impact: float = time + self.DELAY[effect.id]
        super().__init__(effect)
        
    # def get_circles(self, time: float) -> Iterable[DamageCircle]:
    #     time_remaining = self.time + self.delay - time
    #     movement_speed = 1.0
    #     for radius, damage in self.CIRCLES[self.effect.id]:
    #         radius_adjusted = radius - movement_speed * time_remaining
    #         yield DamageCircle(self.position, radius_adjusted, damage)

class DodgeBehavior(UnitBehavior):

    def __init__(self, ai: AIBase, unit_tag: int):
        self.safety_distance: float = 1.0
        super().__init__(ai, unit_tag)

    def execute_single(self, unit: Unit) -> BehaviorResult:
        
        # dodge = min((c for d in self.ai.dodge for c in d.circles), key = lambda c : unit.distance_to(c.position))

        # if dodge_threat < unit.health + unit.shield:
        #     return BehaviorResult.SUCCESS

        for dodge in self.ai.dodge:
            distance_bonus = 0.0
            if isinstance(dodge, DodgeEffectDelayed):
                time_remaining = max(0, dodge.time_of_impact - self.ai.time)
                distance_bonus = 1.4 * unit.movement_speed * time_remaining
            distance = unit.distance_to(dodge.position)
            for circle in dodge.circles:
                if distance + distance_bonus < circle.radius + unit.radius + self.safety_distance:
                    target = unit.position.towards(dodge.position, -3)
                    if unit.is_burrowed and not can_move(unit):
                        unit(AbilityId.BURROWUP)
                        unit.move(target, queue=True)
                    else:
                        unit.move(target)
                    return BehaviorResult.ONGOING

        return BehaviorResult.SUCCESS