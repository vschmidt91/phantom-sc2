
from typing import Optional, Set, Union, Iterable, Tuple
import numpy as np
import random
from sc2.constants import ALL_GAS, SPEED_INCREASE_ON_CREEP_DICT

from sc2.position import Point2
from sc2.unit import Unit
from sc2.unit_command import UnitCommand
from sc2.data import race_worker
from abc import ABC, abstractmethod

from ..utils import *
from ..constants import *
from .behavior import Behavior, BehaviorResult

class GatherBehavior(Behavior):

    def __init__(self, bot):
        self.bot = bot
        self.speed_mining_enabled: bool = True

    def execute(self, unit: Unit) -> BehaviorResult:

        if unit.type_id != race_worker[self.bot.race]:
            return BehaviorResult.FAILURE
        
        resource = self.bot.bases.get_resource(unit.tag)
        if not resource:
            return BehaviorResult.FAILURE

        if not resource.remaining:
            return BehaviorResult.FAILURE

        resource_unit = self.bot.gas_building_by_position.get(resource.position) or self.bot.resource_by_position.get(resource.position)
        if not resource_unit:
            return BehaviorResult.FAILURE

        if not self.bot.townhalls.ready.exists:
            return BehaviorResult.FAILURE
            
        if self.speed_mining_enabled and resource.harvester_balance < 0:
            
            if unit.is_gathering and unit.order_target != resource_unit.tag:
                unit(AbilityId.SMART, resource_unit)
            elif unit.is_idle or unit.is_attacking:
                unit(AbilityId.SMART, resource_unit)
            elif len(unit.orders) == 1:
                if unit.is_returning:
                    target = self.bot.townhalls.ready.closest_to(unit)
                    move_target = None
                else:
                    target = unit
                    move_target = resource.speed_mining_position
                move_target = move_target or target.position.towards(unit, target.radius + unit.radius)
                    
                if 0.75 < unit.position.distance_to(move_target) < 2:
                    unit.move(move_target)
                    unit(AbilityId.SMART, target, True)

        else:
                
            if unit.is_carrying_resource:
                if not unit.is_returning:
                    unit.return_resource()
            elif unit.is_returning:
                pass
            else:
                unit.gather(resource_unit)

        return BehaviorResult.ONGOING