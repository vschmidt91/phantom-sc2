from __future__ import annotations
from sre_constants import SUCCESS
from typing import Optional, Set, Union, Iterable, Tuple, TYPE_CHECKING
import numpy as np
import random

from numpy.lib.arraysetops import isin
from sc2.constants import ALL_GAS, SPEED_INCREASE_ON_CREEP_DICT

from sc2.unit import Unit
from sc2.unit_command import UnitCommand

from src.units.unit import AIUnit

from ..resources.resource_unit import ResourceUnit
from ..utils import *
from ..constants import *
if TYPE_CHECKING:
    from ..ai_base import AIBase

class GatherBehavior(AIUnit):

    def __init__(self, ai: AIBase, tag: int):
        super().__init__(ai, tag)
        self.target: Optional[ResourceUnit] = None
        self.command_queue: Optional[Unit] = None

    def gather(self) -> Optional[UnitCommand]:
        
        if not self.target:
            return None
        elif not self.target.remaining:
            return None
        elif not self.unit.is_carrying_resource:
            return self.unit.gather(self.target.gather_target)
        else:
            return self.unit.return_resource()

        # if not self.ai.townhalls.ready.exists:
        #     return None
        # townhall = self.ai.townhalls.ready.closest_to(self.unit)
            
        # if base.townhall and self.ai.is_speedmining_enabled and resource.harvester_count < 3:

        #     if self.unit.is_gathering and self.unit.order_target != target.tag:
        #         return self.unit.smart(target)
        #     elif self.unit.is_idle or self.unit.is_attacking:
        #         return self.unit.smart(target)
        #     elif self.unit.is_moving and self.command_queue:
        #         self.command_queue, target = None, self.command_queue
        #         return self.unit.smart(target, queue=True)
        #     elif len(self.unit.orders) == 1:
        #         if self.unit.is_returning:
        #             townhall = self.ai.townhalls.ready.closest_to(self.unit)
        #             move_target = townhall.position.towards(self.unit, townhall.radius + self.unit.radius)
        #             if 0.75 < self.unit.position.distance_to(move_target) < 1.5:
        #                 self.command_queue = townhall
        #                 return self.unit.move(move_target)
        #                 # 
        #                 # self.unit(AbilityId.SMART, townhall, True)
        #         else:
        #             move_target = None
        #             if isinstance(resource, MineralPatch):
        #                 move_target = resource.speedmining_target
        #             if not move_target:
        #                 move_target = target.position.towards(self.unit, target.radius + self.unit.radius)
        #             if 0.75 < self.unit.position.distance_to(move_target) < 1.75:
        #                 self.command_queue = target
        #                 return self.unit.move(move_target)
        #                 # self.unit.move(move_target)
        #                 # self.unit(AbilityId.SMART, target, True)

        # else: