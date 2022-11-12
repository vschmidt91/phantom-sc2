from __future__ import annotations

import math
from typing import TYPE_CHECKING, Optional
from scipy.ndimage import gaussian_filter

import numpy as np
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit, UnitCommand

from ..units.unit import AIUnit
from ..modules.module import AIModule
from ..constants import ENERGY_COST

if TYPE_CHECKING:
    from ..ai_base import AIBase

TUMOR_RANGE = 10

class CreepBehavior(AIUnit):

    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)
        self.creation_step = self.ai.state.game_loop

    def spread_creep(self) -> Optional[UnitCommand]:

        if self.unit.type_id == UnitTypeId.CREEPTUMORBURROWED:
            age = self.ai.state.game_loop - self.creation_step
            if age < 240:
                return None
        elif self.unit.type_id == UnitTypeId.QUEEN:
            if self.unit.energy < ENERGY_COST[AbilityId.BUILD_CREEPTUMOR_QUEEN]:
                return None
            elif self.unit.is_using_ability(AbilityId.BUILD_CREEPTUMOR_QUEEN):
                return self.unit(AbilityId.BUILD_CREEPTUMOR_QUEEN, target=self.unit.order_target)
        else:
            return None

        start_position = self.unit.position
        if self.unit.type_id == UnitTypeId.QUEEN:
            if self.ai.townhalls.ready:
                start_position = self.ai.townhalls.ready.random.position

        creep_min = [
            self.ai.game_info.playable_area.x,
            self.ai.game_info.playable_area.y,
        ]
        creep_max = [
            self.ai.game_info.playable_area.right,
            self.ai.game_info.playable_area.top,
        ]

        target = None
        for _ in range(10):
            angle = np.random.uniform(0, 2 * math.pi)
            distance = np.random.exponential(0.5 * TUMOR_RANGE)
            target_test = start_position + distance * Point2((math.cos(angle), math.sin(angle)))
            target_test = np.clip(target_test, creep_min, creep_max)
            target_test = Point2(target_test).rounded

            if self.ai.has_creep(target_test):
                continue
            if not self.ai.in_pathing_grid(target_test):
                continue
            target = target_test
            break

        if not target:
            return None

        if self.unit.type_id == UnitTypeId.QUEEN:
            max_range = 3 * TUMOR_RANGE
        else:
            max_range = TUMOR_RANGE
        max_range = min(max_range, int(self.unit.position.distance_to(target)))

        for i in range(max_range, 0, -1):
            position = self.unit.position.towards(target, i)
            if not self.ai.has_creep(position):
                continue
            if not self.ai.is_visible(position):
                continue
            if not self.ai.in_pathing_grid(position):
                continue
            if any(self.ai.blocked_bases(position, 1.0)):
                continue

            return self.unit.build(UnitTypeId.CREEPTUMOR, position)

        return None