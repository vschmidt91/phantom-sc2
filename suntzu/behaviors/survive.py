
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

    def get_gradient(self, unit: Unit) -> Point2:

        distance_gradient = Point2(self.bot.distance_gradient_map[unit.position.rounded[0], unit.position.rounded[1],:])
        if 0 < distance_gradient.length:
            distance_gradient = distance_gradient.normalized

        enemy_gradient = Point2(self.bot.enemy_gradient_map[unit.position.rounded[0], unit.position.rounded[1],:])
        if 0 < enemy_gradient.length:
            enemy_gradient = enemy_gradient.normalized

        gradient = distance_gradient + enemy_gradient
        if 0 < gradient.length:
            gradient = gradient.normalized
        elif 0 < unit.position.distance_to(self.bot.start_location):
            gradient = (self.bot.start_location - unit.position).normalized

        return gradient

    def execute(self, unit: Unit) -> BehaviorResult:

        last_attacked = self.bot.damage_taken.get(unit.tag)
        if not last_attacked:
            return BehaviorResult.SUCCESS
        if last_attacked + 3 < self.bot.time:
            return BehaviorResult.SUCCESS
        
        gradient = self.get_gradient(unit)
        retreat_target = unit.position - 12 * gradient
        unit.move(retreat_target)
        return BehaviorResult.ONGOING