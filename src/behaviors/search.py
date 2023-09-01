from __future__ import annotations

import random
from typing import Optional

import numpy as np
from sc2.unit_command import UnitCommand
from sc2.position import Point2
from sc2.ids.unit_typeid import UnitTypeId

from ..units.unit import AIUnit, Behavior


class SearchBehavior(Behavior):
    def __init__(self, unit: AIUnit):
        super().__init__(unit)

    def search(self) -> Optional[UnitCommand]:

        if not self.unit.state.is_idle:
            return None
        
        # elif self.ai.all_enemy_units.exists:
        #     target = self.ai.all_enemy_units.random
        #     return self.unit.state.attack(target.position)

        target = self.unit.state.position
        target = target.towards(
            self.ai.game_info.map_center, 1.0 * self.unit.state.movement_speed
        )
        target = np.random.normal(loc=target, scale=self.unit.state.sight_range)
        target = np.clip(target, 0, np.subtract(self.ai.game_info.map_size, 1))
        target_point = Point2(target)
        if not self.unit.state.is_flying and not self.ai.in_pathing_grid(target_point):
            return None
        dps_map = self.ai.combat.air_dps if self.unit.state.is_flying else self.ai.combat.ground_dps
        if 0 < dps_map[target_point.rounded]:
            return None
        if self.ai.is_visible(target_point):
            return None
        return self.unit.state.attack(target_point)

                # a = self.ai.game_info.playable_area
                # target = np.random.uniform((a.x, a.y), (a.right, a.top))
                # target = Point2(target)
                # if (
                #     self.unit.state.is_flying or self.ai.in_pathing_grid(target)
                # ) and not self.ai.is_visible(target):
                #     return self.unit.state.attack(target)

        return None
