
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

class BurrowBehavior(Behavior):

    def execute(self, unit: Unit) -> BehaviorResult:

        if unit.type_id not in { UnitTypeId.ROACH, UnitTypeId.ROACHBURROWED }:
            return BehaviorResult.FAILURE

        if unit.is_burrowed:
            if unit.health_percentage == 1:
                unit(AbilityId.BURROWUP)
                return BehaviorResult.SUCCESS
            elif UpgradeId.TUNNELINGCLAWS in unit._bot_object.state.upgrades:
                return BehaviorResult.FAILURE
            return BehaviorResult.ONGOING
        elif (
            unit.health_percentage < 1/3
            and UpgradeId.BURROW in unit._bot_object.state.upgrades
            and unit.weapon_cooldown
        ):
            unit(AbilityId.BURROWDOWN)
            return BehaviorResult.ONGOING

        return BehaviorResult.FAILURE