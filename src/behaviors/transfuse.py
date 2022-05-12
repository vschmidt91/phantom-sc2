
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

from src.units.unit import CommandableUnit

from ..utils import *
from ..constants import *
from .behavior import Behavior
from ..ai_component import AIComponent
if TYPE_CHECKING:
    from ..ai_base import AIBase

class TransfuseBehavior(CommandableUnit):

    ABILITY = AbilityId.TRANSFUSION_TRANSFUSION
    
    def __init__(self, ai: AIBase, tag: int):
        super().__init__(ai, tag)

    def priority(self, target: Unit) -> float:
        if self.unit.tag == target.tag:
            return 0
        if not self.unit.in_ability_cast_range(self.ABILITY, target):
            return 0
        if BuffId.TRANSFUSION in target.buffs:
            return 0
        if target.health_max <= target.health + 75:
            return 0
        priority = 1
        priority *= 10 + self.ai.get_unit_value(target)
        priority /= .1 + target.health_percentage
        return priority

    def transfuse(self) -> Optional[UnitCommand]:

        if self.unit.energy < ENERGY_COST[self.ABILITY]:
            return None

        target = max(self.ai.all_own_units,
            key = lambda t : self.priority(t),
            default = None
        )
        if not target:
            return None
        if self.priority(target) <= 0:
            return None

        return self.unit(self.ABILITY, target=target)