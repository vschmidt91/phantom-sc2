from __future__ import annotations
from typing import Optional, Set, Union, Iterable, Tuple, TYPE_CHECKING
import numpy as np
import random
from sc2.constants import SPEED_INCREASE_ON_CREEP_DICT
from sc2.ids.buff_id import BuffId

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

class SurviveBehavior(UnitBehavior):

    def __init__(self, ai: AIBase, unit_tag: int):
        super().__init__(ai, unit_tag)

    def execute_single(self, unit: Unit) -> BehaviorResult:

        # if unit.type_id == UnitTypeId.OVERLORD:
        #     unit(AbilityId.BEHAVIOR_GENERATECREEPON)

        if unit.type_id != race_worker[self.ai.race]:
            return BehaviorResult.SUCCESS

        if unit.tag not in self.ai.unit_manager.drafted_civilians:
            return BehaviorResult.SUCCESS

        last_attacked = self.ai.damage_taken.get(unit.tag)
        if not last_attacked:
            return BehaviorResult.SUCCESS
        if last_attacked + 3 < self.ai.time:
            return BehaviorResult.SUCCESS
        
        if self.ai.townhalls:
            retreat_goal = self.ai.townhalls.closest_to(unit.position).position
        else:
            retreat_goal = self.ai.start_location
        retreat_path = self.ai.map_analyzer.pathfind(
            start = unit.position,
            goal = retreat_goal,
            grid = self.ai.enemy_influence_map,
            large = False,
            smoothing = False,
            sensitivity = 1)

        if retreat_path and 2 <= len(retreat_path):
            unit.move(retreat_path[1])
            return BehaviorResult.ONGOING

        return BehaviorResult.FAILURE