
from typing import Optional, Set, Union, Iterable, Tuple
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
from .behavior import Behavior, BehaviorResult

class SurviveBehavior(Behavior):

    def __init__(self, bot):
        self.bot = bot

    def execute(self, unit: Unit) -> BehaviorResult:

        last_attacked = self.bot.damage_taken.get(unit.tag)
        if not last_attacked:
            return BehaviorResult.SUCCESS
        if last_attacked + 3 < self.bot.time:
            return BehaviorResult.SUCCESS
        
        if self.bot.townhalls:
            retreat_goal = self.bot.townhalls.closest_to(unit.position).position
        else:
            retreat_goal = self.bot.start_location
        retreat_path = self.bot.map_analyzer.pathfind(
            start = unit.position,
            goal = retreat_goal,
            grid = self.bot.enemy_influence_map,
            large = False,
            smoothing = False,
            sensitivity = 1)

        if retreat_path and 2 <= len(retreat_path):
            unit.move(retreat_path[1])
            return BehaviorResult.ONGOING

        return BehaviorResult.FAILURE