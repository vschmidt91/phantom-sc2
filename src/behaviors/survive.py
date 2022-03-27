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

        if unit.type_id == UnitTypeId.OVERLORD:
            unit(AbilityId.BEHAVIOR_GENERATECREEPON)

        # if unit.type_id != race_worker[self.ai.race]:
        #     return BehaviorResult.SUCCESS

        last_attacked = self.ai.damage_taken.get(unit.tag)
        if not last_attacked:
            return BehaviorResult.SUCCESS
        if last_attacked + 30 < self.ai.time:
            return BehaviorResult.SUCCESS
        
        if self.ai.townhalls:
            retreat_goal = self.ai.townhalls.closest_to(unit.position).position
        else:
            retreat_goal = self.ai.start_location

        if unit.is_flying:
            enemy_map = self.ai.enemy_vs_air_map
        else:
            enemy_map = self.ai.enemy_vs_ground_map
        retreat_path = self.ai.map_analyzer.pathfind(
            start = unit.position,
            goal = retreat_goal,
            grid = enemy_map,
            large = False,
            smoothing = False,
            sensitivity = 1)

        if retreat_path:
            target = retreat_path[min(3, len(retreat_path) - 1)]
        else:
            target = retreat_goal

        unit.move(target)
        return BehaviorResult.ONGOING