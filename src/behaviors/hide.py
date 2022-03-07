from __future__ import annotations
from typing import List, Optional, Set, Union, Iterable, Tuple, TYPE_CHECKING
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
from .behavior import BehaviorResult, UnitBehavior
from ..ai_component import AIComponent
if TYPE_CHECKING:
    from ..ai_base import AIBase

class HideBehavior(UnitBehavior):

    def __init__(self, ai: AIBase, unit_tag: int):
        super().__init__(ai, unit_tag)
        w, h = ai.game_info.map_size
        corner_candidates: List[Point2] = [
            Point2((0, 0)),
            Point2((0, h)),
            Point2((w, 0)),
            Point2((w, h)),
        ]
        self.corner = ai.start_location

    def execute_single(self, unit: Unit) -> BehaviorResult:

        if unit.type_id is not UnitTypeId.MUTALISK:
            return BehaviorResult.SUCCESS

        if 7 * 60 < self.ai.time:
            return BehaviorResult.SUCCESS

        if unit.distance_to(self.corner) < 3:
            return BehaviorResult.SUCCESS

        unit.move(self.corner)
        return BehaviorResult.ONGOING