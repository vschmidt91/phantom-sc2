from __future__ import annotations
from typing import Optional, Set, Union, Iterable, Tuple, TYPE_CHECKING
import numpy as np
import random
from sc2.constants import SPEED_INCREASE_ON_CREEP_DICT

from sc2.position import Point2
from sc2.unit import Unit
from sc2.unit_command import UnitCommand
from sc2.data import race_worker
from abc import ABC, abstractmethod

from ..utils import *
from ..constants import *
from .behavior import Behavior, BehaviorResult, UnitBehavior
from ..ai_component import AIComponent
if TYPE_CHECKING:
    from ..ai_base import AIBase

class SearchBehavior(UnitBehavior):

    def __init__(self, ai: AIBase, unit_tag: int):
        super().__init__(ai, unit_tag)

    def execute_single(self, unit: Unit) -> BehaviorResult:

        if unit.type_id == UnitTypeId.OVERLORD:
            return BehaviorResult.SUCCESS

        if not unit.is_idle:
            pass
        elif self.ai.time < 8 * 60:
            unit.attack(random.choice(self.ai.enemy_start_locations))
        else:
            unit.attack(random.choice(self.ai.expansion_locations_list))

        return BehaviorResult.ONGOING
            