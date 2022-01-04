from __future__ import annotations
import math

from typing import Iterable, Optional, List, TYPE_CHECKING, Set
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit, UnitCommand
from abc import ABC, abstractmethod
from enum import Enum
import numpy as np

from .behavior import Behavior, UnitBehavior, BehaviorResult

from ..ai_component import AIComponent

if TYPE_CHECKING:
    from ..ai_base import AIBase

class SpreadCreepBehavior(UnitBehavior):

    CREEP_RANGE = 10

    def __init__(self, ai: AIBase, unit_tag: int):
        super().__init__(ai, unit_tag)

    def execute_single(self, unit: Unit) -> BehaviorResult:

        a = self.ai.game_info.playable_area

        if .95 < self.ai.creep_coverage:
            return BehaviorResult.SUCCESS

        if unit.type_id is UnitTypeId.CREEPTUMORBURROWED:
            if AbilityId.BUILD_CREEPTUMOR_TUMOR not in self.ai.abilities[unit.tag]:
                return BehaviorResult.SUCCESS
        elif unit.type_id is UnitTypeId.QUEEN:
            if 10 <= len(self.ai.tumor_front_tags):
                return BehaviorResult.SUCCESS
            elif AbilityId.BUILD_CREEPTUMOR_QUEEN not in self.ai.abilities[unit.tag]:
                return BehaviorResult.SUCCESS
            elif AbilityId.BUILD_CREEPTUMOR_QUEEN in { o.ability.exact_id for o in unit.orders }:
                return BehaviorResult.ONGOING
            elif not self.ai.has_creep(unit.position) and self.ai.townhalls.ready:
                if not unit.is_moving:
                    unit.move(self.ai.townhalls.ready.closest_to(unit)) 
                return BehaviorResult.ONGOING
        else:
            return BehaviorResult.SUCCESS

        start_position = unit.position
        if unit.type_id == UnitTypeId.QUEEN:
            if self.ai.townhalls.ready:
                start_position = self.ai.townhalls.ready.random.position

        target = None
        for _ in range(10):
            angle = np.random.uniform(0, 2 * math.pi)
            distance = np.random.exponential(0.5 * self.CREEP_RANGE)
            target_test = start_position + distance * Point2((math.cos(angle), math.sin(angle)))
            target_test = np.clip(target_test, self.ai.creep_area_min, self.ai.creep_area_max)
            target_test = Point2(target_test).rounded
            
            if self.ai.has_creep(target_test):
                continue
            if not self.ai.in_pathing_grid(target_test):
                continue
            target = target_test
            break

        if not target:
            return BehaviorResult.SUCCESS

        if unit.type_id == UnitTypeId.QUEEN:
            max_range = 3 * self.CREEP_RANGE
        else:
            max_range = self.CREEP_RANGE
        max_range = min(max_range, int(unit.position.distance_to(target)))

        for i in range(max_range, 0, -1):
            position = unit.position.towards(target, i)
            if not self.ai.has_creep(position):
                continue
            if not self.ai.is_visible(position):
                continue
            if not self.ai.in_pathing_grid(position):
                continue
            if self.ai.blocked_base(position):
                continue
            unit.build(UnitTypeId.CREEPTUMOR, position)
            return BehaviorResult.ONGOING

        return BehaviorResult.SUCCESS
