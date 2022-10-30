from __future__ import annotations

import random
import numpy as np
from typing import Optional, TYPE_CHECKING

from sc2.unit_command import UnitCommand

from ..constants import *
from ..units.unit import AIUnit
from ..utils import *

if TYPE_CHECKING:
    from ..ai_base import AIBase


class SearchBehavior(AIUnit):

    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)

    def search(self) -> Optional[UnitCommand]:

        if self.unit.type_id == UnitTypeId.OVERLORD:
            return None

        if self.unit.is_idle:
            if self.ai.combat.confidence < 1/2:
                if target := next((b for b in reversed(self.ai.resource_manager.bases) if b.townhall), None):
                    return self.unit.attack(target.position)
            elif self.ai.time < 8 * 60:
                return self.unit.attack(random.choice(self.ai.enemy_start_locations))
            else:
                a = self.ai.game_info.playable_area
                target = np.random.uniform((a.x, a.y), (a.right, a.top))
                target = Point2(target)
                if (
                        (self.unit.is_flying or self.ai.in_pathing_grid(target))
                        and not self.ai.is_visible(target)
                ):
                    return self.unit.attack(target)


        return None