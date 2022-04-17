from __future__ import annotations
from typing import Optional, Set, Union, Iterable, Tuple, TYPE_CHECKING
import numpy as np
import random

from s2clientprotocol.common_pb2 import Point
from sc2.constants import SPEED_INCREASE_ON_CREEP_DICT

from sc2.position import Point2
from sc2.unit import Unit
from sc2.unit_command import UnitCommand
from sc2.data import race_worker
from abc import ABC, abstractmethod

from ..utils import *
from ..constants import *
from .behavior import Behavior
from ..ai_component import AIComponent
if TYPE_CHECKING:
    from ..ai_base import AIBase

class LaunchCorrosiveBilesBehavior(Behavior):

    ABILITY = AbilityId.EFFECT_CORROSIVEBILE

    def __init__(self, ai: AIBase, unit_tag: int):
        super().__init__(ai, unit_tag)
        self.last_used = 0

    def target_priority(self, unit: Unit, target: Unit):
        if not self.ai.is_visible(target.position):
            return 0
        if not unit.in_ability_cast_range(self.ABILITY, target.position):
            return 0
        if target.is_hallucination:
            return 0
        if target.type_id in CHANGELINGS:
            return 0
        priority = 10 + max(target.ground_dps, target.air_dps)
        priority /= 100 + target.health + target.shield
        priority /= 2 + target.movement_speed
        return priority

    def execute_single(self, unit: Unit) -> Optional[UnitCommand]:

        if unit.type_id is not UnitTypeId.RAVAGER:
            return None

        # if self.ABILITY in { o.ability.exact_id for o in unit.orders }:
        #     return BehaviorResult.ONGOING

        if self.ai.state.game_loop < self.last_used + COOLDOWN[AbilityId.EFFECT_CORROSIVEBILE]:
            return None

        targets = (
            target
            for target in self.ai.enumerate_enemies()
        )
        target: Unit = max(targets,
            key = lambda t : self.target_priority(unit, t),
            default = None
        )
        if not target:
            return None
        if self.target_priority(unit, target) <= 0:
            return None
        velocity = self.ai.estimate_enemy_velocity(target)
        if 2 < velocity.length:
            velocity = Point2((0, 0))
        predicted_position = target.position + velocity * 50 / 22.4
        self.last_used = self.ai.state.game_loop
        return unit(self.ABILITY, target=predicted_position)