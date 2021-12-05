from __future__ import annotations
from datetime import time
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
from suntzu.behaviors.behavior import Behavior, BehaviorResult, UnitBehavior
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

class DamageCircle(object):

    def __init__(self, position: Point2, radius: float, damage: float):
        self.position: Point2 = position
        self.radius: float = radius
        self.damage: float = damage

class DodgeElement(ABC):

    SAFETY_DISTANCE = 3.0
    
    @abstractmethod
    def add_damage(self, analyzer, grid: np.ndarray, time: float) -> np.ndarray:
        raise NotImplementedError

class DodgeUnit(DodgeElement):

    RADIUS: Dict[UnitTypeId, float] = {
        UnitTypeId.DISRUPTORPHASED: 1.5,
        UnitTypeId.BANELING: 2.2,
    }

    DAMAGE: Dict[UnitTypeId, float] = {
        UnitTypeId.DISRUPTORPHASED: 145.0,
        UnitTypeId.BANELING: 19.0,
    }

    def __init__(self, unit: Unit):
        self.unit = unit
        super().__init__()

    def add_damage(self, analyzer, grid: np.ndarray, time: float) -> np.ndarray:
        position = self.unit.position
        radius = self.RADIUS[self.unit.type_id] + self.SAFETY_DISTANCE
        damage = self.DAMAGE[self.unit.type_id]
        grid = analyzer.add_cost(position, radius, grid, damage)
        return grid

class DodgeEffect(DodgeElement):

    DAMAGE: Dict[EffectId, float] = {
        EffectId.LURKERMP: 20.0,
        EffectId.PSISTORMPERSISTENT: 80.0,
    }

    def __init__(self, effect: EffectData):
        self.effect = effect
        super().__init__()

    def get_circles(self, time: float) -> Iterable[DamageCircle]:
        radius = self.effect.radius
        damage = self.DAMAGE[self.effect.id]
        for position in self.effect.positions:
            yield DamageCircle(position, radius, damage)

    def add_damage(self, analyzer, grid: np.ndarray, time: float) -> np.ndarray:
        for circle in self.get_circles(time):
            position = circle.position
            radius = circle.radius + self.SAFETY_DISTANCE
            damage = circle.damage
            if radius < 0:
                continue
            grid = analyzer.add_cost(position, radius, grid, damage)
        return grid

class DodgeEffectDelayed(DodgeEffect):

    DELAY: Dict[EffectId, float] = {
        EffectId.RAVAGERCORROSIVEBILECP: 50 / 22.4,
        EffectId.NUKEPERSISTENT: 320 / 22.4,
    }

    CIRCLES: Dict[EffectId, List[Tuple[float, float]]] = {
        EffectId.RAVAGERCORROSIVEBILECP: [
            (0, 60)
        ],
        EffectId.NUKEPERSISTENT: [
            (4, 150),
            (6, 75),
            (8, 75),
        ],
    }

    def __init__(self, effect: EffectData, time: float):
        self.time: float = time
        super().__init__(effect)

    @property
    def delay(self) -> float:
        return self.DELAY[self.effect.id]

    @property
    def position(self) -> Point2:
        return next(iter(self.effect.positions))
        
    def get_circles(self, time: float) -> Iterable[DamageCircle]:
        time_remaining = self.time + self.delay - time
        movement_speed = 0
        for radius, damage in self.CIRCLES[self.effect.id]:
            radius_adjusted = radius - movement_speed * time_remaining
            yield DamageCircle(self.position, radius_adjusted, damage)

class DodgeBehavior(UnitBehavior):

    def __init__(self, ai: AIBase, unit_tag: int):
        super().__init__(ai, unit_tag)

    def execute_single(self, unit: Unit) -> BehaviorResult:

        p = unit.position.rounded
        dodge_threat = self.ai.dodge_map[p]
        if dodge_threat == np.inf:
            return BehaviorResult.FAILURE
        if dodge_threat <= 1:
            return BehaviorResult.FAILURE

        # if dodge_threat < unit.health + unit.shield:
        #     return BehaviorResult.FAILURE

        path = self.ai.map_analyzer.pathfind(
            start = unit.position,
            goal = self.ai.start_location,
            grid = self.ai.dodge_map,
            large = is_large(unit),
            smoothing = False,
            sensitivity = 1)

        if not path:
            return BehaviorResult.FAILURE

        target = path[min(3, len(path) - 1)]
        if unit.is_burrowed and not can_move(unit):
            unit(AbilityId.BURROWUP)
            unit.move(target, queue=True)
        else:
            unit.move(target)

        return BehaviorResult.ONGOING