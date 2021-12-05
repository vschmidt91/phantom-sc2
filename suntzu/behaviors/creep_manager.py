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

from suntzu.behaviors.behavior import Behavior, UnitBehavior, BehaviorResult

from ..ai_component import AIComponent

if TYPE_CHECKING:
    from ..ai_base import AIBase

class CreepManager(Behavior):

    def __init__(self, ai: AIBase):
        super().__init__()
        self.ai: AIBase = ai
        self.behavior = SpreadCreapBehavior(ai, 0)
        self.queens: Set[int] = set()

    def execute(self) -> BehaviorResult:

        creep_coverage = np.sum(self.ai.state.creep.data_numpy) / self.ai.creep_tile_count
        if .95 < creep_coverage:
            return 

        spreaders = list()

        for tumor in self.ai.actual_by_type[UnitTypeId.CREEPTUMORBURROWED]:
            if AbilityId.BUILD_CREEPTUMOR_TUMOR in self.ai.abilities[tumor.tag]:
                spreaders.append(tumor)

        for tag in self.queens:
            queen = self.ai.unit_by_tag[tag]
            if (
                not self.ai.has_creep(queen.position)
                and not queen.is_moving
                and self.ai.townhalls.ready
            ):
                townhall = self.ai.townhalls.ready.closest_to(queen)
                queen.move(townhall)     
            elif (
                AbilityId.BUILD_CREEPTUMOR_QUEEN in self.ai.abilities[tag]
                and AbilityId.BUILD_CREEPTUMOR_QUEEN not in { o.ability.exact_id for o in queen.orders }
            ):
                spreaders.append(queen)

        for spreader in spreaders:
            self.behavior.unit_tag = spreader.tag
            self.behavior.execute()

        return BehaviorResult.ONGOING

class SpreadCreapBehavior(UnitBehavior):

    CREEP_RANGE = 10

    def __init__(self, ai: AIBase, unit_tag: int):
        super().__init__(ai, unit_tag)

    def execute_single(self, unit: Unit) -> BehaviorResult:

        start_position = unit.position
        if unit.type_id == UnitTypeId.QUEEN:
            forward_base = max(
                self.ai.townhalls.ready,
                key = lambda th : self.ai.distance_map[th.position.rounded],
                default = None)
            if forward_base:
                start_position = forward_base.position 

        target = None
        for _ in range(3):
            angle = np.random.uniform(0, 2 * math.pi)
            distance = np.random.exponential(self.CREEP_RANGE)
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
            return

        if unit.type_id == UnitTypeId.QUEEN:
            max_range = 3 * self.CREEP_RANGE
        else:
            max_range = self.CREEP_RANGE

        for i in range(max_range, 0, -1):
            position = unit.position.towards(target, i)
            if not self.ai.has_creep(position):
                continue
            if not self.ai.is_visible(position):
                continue
            if self.ai.blocked_base(position):
                continue
            unit.build(UnitTypeId.CREEPTUMOR, position)
            # self.tumor_front.difference_update((unit.tag,))
            break