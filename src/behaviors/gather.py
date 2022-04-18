from __future__ import annotations
from sre_constants import SUCCESS
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

from ..resources.vespene_geyser import VespeneGeyser

from ..resources.mineral_patch import MineralPatch
from ..utils import *
from ..constants import *
from .behavior import Behavior
from ..ai_component import AIComponent
if TYPE_CHECKING:
    from ..ai_base import AIBase

class GatherBehavior(Behavior):

    def __init__(self, ai: AIBase, unit_tag: int):
        super().__init__(ai, unit_tag)
        self.target: Optional[Unit] = None

    def execute_single(self, unit: Unit) -> Optional[UnitCommand]:
        
        resource, base = self.ai.bases.get_resource_and_item(unit.tag)
        if not resource:
            if unit.is_idle:
                raise Exception()
            return None
            # if not self.ai.bases.try_add(unit.tag):
            #     raise Exception()
            # resource, base = self.ai.bases.get_resource_and_item(unit.tag)

        if not resource:
            raise Exception()
        if not resource.remaining:
            return None

        target = self.ai.gas_building_by_position.get(resource.position) or self.ai.resource_by_position.get(resource.position)
        if not target:
            raise Exception()

            
        if base.townhall and self.ai.is_speedmining_enabled and resource.harvester_count < 3:

            if unit.is_gathering and unit.order_target != target.tag:
                return unit.smart(target)
            elif unit.is_idle or unit.is_attacking:
                return unit.smart(target)
            elif unit.is_moving and self.target:
                self.target, target = None, self.target
                return unit.smart(target, queue=True)
            elif len(unit.orders) == 1:
                if unit.is_returning:
                    townhall = self.ai.townhalls.ready.closest_to(unit)
                    move_target = townhall.position.towards(unit, townhall.radius + unit.radius)
                    if 0.75 < unit.position.distance_to(move_target) < 1.5:
                        self.target = townhall
                        return unit.move(move_target)
                        # 
                        # unit(AbilityId.SMART, townhall, True)
                else:
                    move_target = None
                    if isinstance(resource, MineralPatch):
                        move_target = resource.speedmining_target
                    if not move_target:
                        move_target = target.position.towards(unit, target.radius + unit.radius)
                    if 0.75 < unit.position.distance_to(move_target) < 1.75:
                        self.target = target
                        return unit.move(move_target)
                        # unit.move(move_target)
                        # unit(AbilityId.SMART, target, True)

        else:

            if not unit.is_carrying_resource:
                return unit.gather(target)
            elif self.ai.townhalls.ready.exists:
                return unit.return_resource()