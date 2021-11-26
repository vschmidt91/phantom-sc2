
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

class SearchBehavior(Behavior):

    def __init__(self, bot):
        self.bot = bot

    def execute(self, unit: Unit) -> BehaviorResult:

        if not unit.is_idle:
            pass
        elif self.bot.time < 8 * 60:
            unit.attack(random.choice(self.bot.enemy_start_locations))
        else:
            unit.attack(random.choice(self.bot.expansion_locations_list))

        return BehaviorResult.ONGOING
            