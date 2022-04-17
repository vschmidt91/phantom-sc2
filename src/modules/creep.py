from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Optional, Set

import random
import math
import numpy as np

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit, UnitCommand
from sc2.position import Point2
from src.behaviors.behavior import Behavior
from src.constants import COOLDOWN, ENERGY_COST

from .module import AIModule
if TYPE_CHECKING:
    from ..ai_base import AIBase

TUMOR_RANGE = 10
    
class Creep(AIModule):

    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)

        self.area_min: np.ndarray = np.array(self.ai.game_info.map_center)
        self.area_max: np.ndarray = np.array(self.ai.game_info.map_center)
        for base in self.ai.expansion_locations_list:
            self.area_min = np.minimum(self.area_min, base)
            self.area_max = np.maximum(self.area_max, base)
        self.tile_count: int = np.sum(self.ai.game_info.pathing_grid.data_numpy)
        self.coverage: float = 0.0
        self.tumor_front: Dict[int] = dict()

    async def on_step(self) -> None:

        self.coverage = np.sum(self.ai.state.creep.data_numpy) / self.tile_count
    
class SpreadCreep(Behavior):

    def __init__(self, ai: AIBase, unit_tag: int):
        super().__init__(ai, unit_tag)
        self.creation_step = self.ai.state.game_loop

    def execute_single(self, unit: Unit) -> Optional[UnitCommand]:

        a = self.ai.game_info.playable_area

        if .99 < self.ai.creep.coverage:
            return None

        if unit.type_id == UnitTypeId.CREEPTUMORBURROWED:
            age = self.ai.state.game_loop - self.creation_step
            if age < 240:
                return None
        elif unit.type_id == UnitTypeId.QUEEN:
            if 10 <= len(self.ai.creep.tumor_front):
                return None
            elif 1 < self.ai.enemy_vs_ground_map[unit.position.rounded]:
                return None
            elif unit.energy < ENERGY_COST[AbilityId.BUILD_CREEPTUMOR_QUEEN]:
                return None
            elif any(unit.orders) and unit.orders[0].ability.exact_id == AbilityId.BUILD_CREEPTUMOR_QUEEN:
                return unit(AbilityId.BUILD_CREEPTUMOR_QUEEN, target=unit.order_target)
            # elif not self.ai.has_creep(unit.position) and self.ai.townhalls.ready:
            #     if unit.is_moving:
            #         return unit.move(unit.order_target)
            #     else:
            #         return unit.move(self.ai.townhalls.ready.closest_to(unit)) 
        else:
            return None

        start_position = unit.position
        if unit.type_id == UnitTypeId.QUEEN:
            if self.ai.townhalls.ready:
                start_position = self.ai.townhalls.ready.random.position

        target = None
        for _ in range(10):
            angle = np.random.uniform(0, 2 * math.pi)
            distance = np.random.exponential(0.5 * TUMOR_RANGE)
            target_test = start_position + distance * Point2((math.cos(angle), math.sin(angle)))
            target_test = np.clip(target_test, self.ai.creep.area_min, self.ai.creep.area_max)
            target_test = Point2(target_test).rounded
            
            if self.ai.has_creep(target_test):
                continue
            if not self.ai.in_pathing_grid(target_test):
                continue
            target = target_test
            break

        if not target:
            return None

        if unit.type_id == UnitTypeId.QUEEN:
            max_range = 3 * TUMOR_RANGE
        else:
            max_range = TUMOR_RANGE
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

            # if unit.type_id == UnitTypeId.CREEPTUMORBURROWED:
            #     del self.ai.unit_manager.behaviors[unit.tag]

            return unit.build(UnitTypeId.CREEPTUMOR, position)