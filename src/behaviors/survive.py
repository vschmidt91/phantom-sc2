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

from src.units.unit import AIUnit

from ..utils import *
from ..constants import *
from .behavior import Behavior
from ..ai_component import AIComponent
if TYPE_CHECKING:
    from ..ai_base import AIBase

class SurviveBehavior(AIUnit):
    
    def __init__(self, ai: AIBase, tag: int):
        super().__init__(ai, tag)

    def survive(self) -> Optional[UnitCommand]:

        # if unit.type_id == UnitTypeId.OVERLORD:
        #     return unit(AbilityId.BEHAVIOR_GENERATECREEPON)

        # if unit.type_id != race_worker[self.ai.race]:
        #     return BehaviorResult.SUCCESS

        last_attacked = self.ai.damage_taken.get(self.tag)
        if not last_attacked:
            return None
        if last_attacked + 5 < self.ai.time:
            return None
        
        if self.ai.townhalls:
            retreat_goal = self.ai.townhalls.closest_to(self.unit.position).position
        else:
            retreat_goal = self.ai.start_location

        if self.unit.is_flying:
            enemy_map = self.ai.combat.enemy_vs_air_map
        else:
            enemy_map = self.ai.combat.enemy_vs_ground_map
        retreat_path = self.ai.map_analyzer.pathfind(
            start = self.unit.position,
            goal = retreat_goal,
            grid = enemy_map,
            large = False,
            smoothing = False,
            sensitivity = 1)

        if retreat_path:
            target = retreat_path[min(3, len(retreat_path) - 1)]
        else:
            target = retreat_goal

        return self.unit.move(target)