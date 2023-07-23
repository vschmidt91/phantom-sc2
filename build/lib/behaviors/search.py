from __future__ import annotations

import random
from typing import TYPE_CHECKING, Optional

import numpy as np
from sc2.unit_command import UnitCommand
from sc2.position import Point2
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId

from ..units.unit import AIUnit

if TYPE_CHECKING:
    from ..ai_base import AIBase


class SearchBehavior(AIUnit):
    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)

    def search(self) -> Optional[UnitCommand]:
        if self.state.type_id == UnitTypeId.OVERLORD:
            return None

        if self.state.is_idle:
            if self.ai.time < 8 * 60:
                return self.state.attack(random.choice(self.ai.enemy_start_locations))
            elif self.ai.all_enemy_units.exists:
                target = self.ai.all_enemy_units.random
                return self.state.attack(target.position)
            else:
                a = self.ai.game_info.playable_area
                target = np.random.uniform((a.x, a.y), (a.right, a.top))
                target = Point2(target)
                if (
                    self.state.is_flying or self.ai.in_pathing_grid(target)
                ) and not self.ai.is_visible(target):
                    return self.state.attack(target)

        return None
