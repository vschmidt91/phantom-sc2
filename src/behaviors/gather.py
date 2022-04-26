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

from src.units.unit import AIUnit

from ..resources.vespene_geyser import VespeneGeyser

from ..resources.mineral_patch import MineralPatch
from ..utils import *
from ..constants import *
from .behavior import Behavior
from ..ai_component import AIComponent
if TYPE_CHECKING:
    from ..ai_base import AIBase

class GatherBehavior(AIUnit):

    def __init__(self, ai: AIBase, tag: int):
        super().__init__(ai, tag)
        self.target: Optional[Unit] = None

    def gather(self) -> Optional[UnitCommand]:
        
        resource, base = self.ai.bases.get_resource_and_item(self.tag)
        if not resource:
            return None
            # if not self.ai.bases.try_add(unit.tag):
            #     raise Exception()
            # resource, base = self.ai.bases.get_resource_and_item(unit.tag)

        if not resource:
            return None
        if not resource.remaining:
            return None

        target = self.ai.gas_building_by_position.get(resource.position) or self.ai.resource_by_position.get(resource.position)
        if not target:
            return None

            
        if base.townhall and self.ai.is_speedmining_enabled and resource.harvester_count < 3:

            if self.unit.is_gathering and self.unit.order_target != target.tag:
                return self.unit.smart(target)
            elif self.unit.is_idle or self.unit.is_attacking:
                return self.unit.smart(target)
            elif self.unit.is_moving and self.target:
                self.target, target = None, self.target
                return self.unit.smart(target, queue=True)
            elif len(self.unit.orders) == 1:
                if self.unit.is_returning:
                    townhall = self.ai.townhalls.ready.closest_to(self.unit)
                    move_target = townhall.position.towards(self.unit, townhall.radius + self.unit.radius)
                    if 0.75 < self.unit.position.distance_to(move_target) < 1.5:
                        self.target = townhall
                        return self.unit.move(move_target)
                        # 
                        # self.unit(AbilityId.SMART, townhall, True)
                else:
                    move_target = None
                    if isinstance(resource, MineralPatch):
                        move_target = resource.speedmining_target
                    if not move_target:
                        move_target = target.position.towards(self.unit, target.radius + self.unit.radius)
                    if 0.75 < self.unit.position.distance_to(move_target) < 1.75:
                        self.target = target
                        return self.unit.move(move_target)
                        # self.unit.move(move_target)
                        # self.unit(AbilityId.SMART, target, True)

        else:

            if not self.unit.is_carrying_resource:
                return self.unit.gather(target)
            elif self.ai.townhalls.ready.exists:
                return self.unit.return_resource()