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

from ..resources.mineral_patch import MineralPatch
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
        
        resource, base = self.ai.bases.get_resource_and_item(unit.tag)
        if not resource:
            if not self.ai.bases.try_add(unit.tag):
                return BehaviorResult.FAILURE
            resource, base = self.ai.bases.get_resource_and_item(unit.tag)

        if not resource:
            return BehaviorResult.FAILURE
        if not resource.remaining:
            return BehaviorResult.SUCCESS

        target = self.ai.gas_building_by_position.get(resource.position) or self.ai.resource_by_position.get(resource.position)
        if not target:
            return BehaviorResult.FAILURE

            
        if base.townhall and self.ai.is_speedmining_enabled and resource.harvester_count < 3:
            
            if unit.is_gathering and unit.order_target != target.tag:
                unit(AbilityId.SMART, target)
            elif unit.is_idle or unit.is_attacking:
                unit(AbilityId.SMART, target)
            elif len(unit.orders) == 1:
                if unit.is_returning:
                    townhall = self.ai.townhalls.ready.closest_to(unit)
                    move_target = townhall.position.towards(unit, townhall.radius + unit.radius)
                    if 0.75 < unit.position.distance_to(move_target) < 1.5:
                        unit.move(move_target)
                        unit(AbilityId.SMART, townhall, True)
                    else:
                        unit.return_resource()
                else:
                    move_target = None
                    if isinstance(resource, MineralPatch):
                        move_target = resource.speedmining_target
                    if not move_target:
                        move_target = target.position.towards(unit, target.radius + unit.radius)
                    if 0.75 < unit.position.distance_to(move_target) < 1.5:
                        unit.move(move_target)
                        unit(AbilityId.SMART, target, True)

        else:
                
            if unit.is_carrying_resource:
                if not unit.is_returning:
                    unit.return_resource()
            elif unit.is_gathering:
                if unit.order_target != target.tag:
                    unit.gather(target)
            else:
                unit.gather(target)

            # if unit.is_carrying_resource:
            #     if not unit.is_returning:
            #         unit.return_resource()
            # elif unit.is_returning:
            #     pass
            # else:
            #     unit.gather(target)

        return BehaviorResult.ONGOING