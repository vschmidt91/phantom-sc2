
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
from ..utils import *

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

    def __init__(self, bot):
        self.bot = bot

    def execute(self, unit: Unit) -> BehaviorResult:

        p = unit.position.rounded
        dodge_threat = self.bot.dodge_map[p]
        if dodge_threat <= 0:
            return BehaviorResult.FAILURE

        dodge_gradient = self.bot.dodge_gradient_map[p[0],p[1],:]
        dodge_gradient = Point2(dodge_gradient)
        if dodge_gradient.length == 0:
            return BehaviorResult.FAILURE

        dodge_gradient = dodge_gradient.normalized

        target = unit.position - 2 * dodge_gradient
        if unit.is_burrowed and not can_move(unit):
            unit(AbilityId.BURROWUP)
            unit.move(target, queue=True)
        else:
            unit.move(target)

        return BehaviorResult.ONGOING