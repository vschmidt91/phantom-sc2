
from typing import Optional, Union, List, Iterable

from s2clientprotocol.data_pb2 import AbilityData

from sc2.position import Point2
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.ids.effect_id import EffectId
from sc2.unit import Unit
from sc2.game_state import EffectData
from sc2.unit_command import UnitCommand

from .behavior import Behavior, BehaviorResult

class DodgeElement(object):

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

class DodgeCorrosiveBile(DodgeElement):

    def __init__(self, position: Point2, time: float):
        self.time: float = time
        self.position: Point2 = position
        super().__init__([position], 0.5)

    @property
    def time_of_impact(self):
        return self.time + 50 / 22.4

class DodgeNuke(DodgeElement):

    def __init__(self, position: Point2, time: float):
        self.time: float = time
        self.position: Point2 = position
        super().__init__([position], 8)

    @property
    def time_of_impact(self):
        return self.time + 320 / 22.4

class DodgeBehavior(Behavior):

    def __init__(self, dodge: List[DodgeElement]):
        self.dodge: List[DodgeElement] = dodge
        self.safety_distance: float = 1

    def execute(self, unit: Unit) -> BehaviorResult:
        for dodge in self.dodge:
            for position in dodge.positions:
                dodge_distance = unit.position.distance_to(position) - unit.radius - dodge.radius - self.safety_distance
                if dodge_distance < 0:
                    target = unit.position.towards(position, dodge_distance)
                    unit.move(target)
                    return BehaviorResult.ONGOING
        return BehaviorResult.FAILURE