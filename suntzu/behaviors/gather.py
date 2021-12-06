from __future__ import annotations
from typing import Optional, Set, Union, Iterable, Tuple, TYPE_CHECKING
import numpy as np
import random

from numpy.lib.arraysetops import isin
from sc2.constants import ALL_GAS, SPEED_INCREASE_ON_CREEP_DICT

from sc2.position import Point2
from sc2.unit import Unit
from sc2.unit_command import UnitCommand
from sc2.data import race_worker
from abc import ABC, abstractmethod

from suntzu.resources.mineral_patch import MineralPatch

from ..utils import *
from ..constants import *
from .behavior import Behavior, BehaviorResult, UnitBehavior
from ..ai_component import AIComponent
if TYPE_CHECKING:
    from ..ai_base import AIBase

class GatherBehavior(UnitBehavior):

    def __init__(self, ai: AIBase, unit_tag: int):
        super().__init__(ai, unit_tag)

    def execute_single(self, unit: Unit) -> BehaviorResult:

        if unit.type_id != race_worker[self.ai.race]:
            return BehaviorResult.SUCCESS

        if unit.tag in self.ai.unit_manager.drafted_civilians:
            return BehaviorResult.SUCCESS

        if unit.tag in self.ai.plan_units:
            return BehaviorResult.SUCCESS
        
        resource = self.ai.bases.get_resource(unit.tag)
        if not resource:
            base = min(self.ai.bases, key = lambda b : unit.position.distance_to(b.position))
            if not base.try_add(unit.tag):
                return BehaviorResult.FAILURE
            resource = self.ai.bases.get_resource(unit.tag)

        if not resource.remaining:
            return BehaviorResult.SUCCESS

        resource_unit = self.ai.gas_building_by_position.get(resource.position) or self.ai.resource_by_position.get(resource.position)
        if not resource_unit:
            return BehaviorResult.SUCCESS

        if not self.ai.townhalls.ready.exists:
            return BehaviorResult.SUCCESS
            
        if self.ai.is_speedmining_enabled and resource.harvester_count < 3:
            
            if unit.is_gathering and unit.order_target != resource_unit.tag:
                unit(AbilityId.SMART, resource_unit)
            elif unit.is_idle or unit.is_attacking:
                unit(AbilityId.SMART, resource_unit)
            elif len(unit.orders) == 1:
                if unit.is_returning:
                    target = self.ai.townhalls.ready.closest_to(unit)
                    move_target = None
                else:
                    target = resource_unit
                    if isinstance(resource, MineralPatch):
                        move_target = resource.speedmining_target
                    else:
                        move_target = None
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