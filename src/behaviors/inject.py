from __future__ import annotations
from typing import Optional, Set, Union, Iterable, Tuple, TYPE_CHECKING
import numpy as np
import random
from sc2.constants import ALL_GAS, SPEED_INCREASE_ON_CREEP_DICT

from sc2.position import Point2
from sc2.unit import Unit
from sc2.ids.buff_id import BuffId
from sc2.unit_command import UnitCommand
from sc2.data import race_worker
from abc import ABC, abstractmethod

from ..utils import *
from ..constants import *
from .behavior import Behavior, BehaviorResult, UnitBehavior
from ..ai_component import AIComponent
if TYPE_CHECKING:
    from ..ai_base import AIBase

class InjectBehavior(UnitBehavior):

    def __init__(self, ai: AIBase, unit_tag: int):
        super().__init__(ai, unit_tag)
        self.did_first_inject: bool = False

    def execute_single(self, unit: Unit) -> BehaviorResult:

        if not self.did_first_inject:
            townhall = min(self.ai.townhalls.ready, key = lambda th : th.distance_to(unit), default = None)
            if townhall and BuffId.QUEENSPAWNLARVATIMER not in townhall.buffs:
                unit(AbilityId.EFFECT_INJECTLARVA, target=townhall)
                self.did_first_inject = True
                return BehaviorResult.ONGOING

        townhall_tag = self.ai.unit_manager.inject_queens.get(unit.tag)
        if not townhall_tag:
            return BehaviorResult.SUCCESS

        townhall = self.ai.unit_by_tag.get(townhall_tag)
        if not townhall:
            return BehaviorResult.SUCCESS

        if unit.is_using_ability(AbilityId.EFFECT_INJECTLARVA):
            return BehaviorResult.ONGOING
            
        base = next(b for b in self.ai.bases if b.position == townhall.position)
        if base:
            target = base.position.towards(base.mineral_patches.position, -(townhall.radius + unit.radius))
        else:
            target = townhall.position

        if 1 < unit.position.distance_to(target):
            unit.attack(target)
            return BehaviorResult.ONGOING
        elif AbilityId.EFFECT_INJECTLARVA in self.ai.abilities[unit.tag]:
            unit(AbilityId.EFFECT_INJECTLARVA, target=townhall)
            return BehaviorResult.ONGOING

        return BehaviorResult.ONGOING