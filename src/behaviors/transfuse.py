
from __future__ import annotations
from typing import Optional, Set, Union, Iterable, Tuple, TYPE_CHECKING
import numpy as np
import random

from s2clientprotocol.common_pb2 import Point
from sc2.constants import SPEED_INCREASE_ON_CREEP_DICT

from sc2.position import Point2
from sc2.unit import Unit
from sc2.ids.buff_id import BuffId
from sc2.unit_command import UnitCommand
from sc2.data import race_worker
from abc import ABC, abstractmethod

from ..utils import *
from ..constants import *
from .behavior import Behavior, BehaviorResult, UnitBehavior
from ..ai_component import AIComponent
if TYPE_CHECKING:
    from ..ai_base import AIBase

class TransfuseBehavior(UnitBehavior):

    ABILITY = AbilityId.TRANSFUSION_TRANSFUSION

    def __init__(self, ai: AIBase, unit_tag: int):
        super().__init__(ai, unit_tag)

    def priority(self, queen: Unit, target: Unit) -> float:
        if queen.tag == target.tag:
            return 0
        if not queen.in_ability_cast_range(self.ABILITY, target):
            return 0
        if BuffId.TRANSFUSION in target.buffs:
            return 0
        if target.health_max <= target.health + 75:
            return 0
        priority = 1
        priority *= 10 + self.ai.get_unit_value(target)
        return priority

    def execute_single(self, unit: Unit) -> BehaviorResult:

        if unit.energy < ENERGY_COST[self.ABILITY]:
            return BehaviorResult.SUCCESS

        target = max(self.ai.all_own_units,
            key = lambda t : self.priority(unit, t),
            default = None
        )
        if not target:
            return BehaviorResult.SUCCESS 
        if self.priority(unit, target) <= 0:
            return BehaviorResult.SUCCESS

        unit(self.ABILITY, target=target)
        return BehaviorResult.ONGOING