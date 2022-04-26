from __future__ import annotations
from typing import Optional, Set, Union, Iterable, Tuple, TYPE_CHECKING
import numpy as np
import random
from sc2.constants import SPEED_INCREASE_ON_CREEP_DICT

from sc2.position import Point2
from sc2.unit import Unit
from sc2.unit_command import UnitCommand
from sc2.data import race_worker
from abc import ABC, abstractmethod

from ..units.unit import AIUnit

from ..utils import *
from ..constants import *
from .behavior import Behavior
from ..ai_component import AIComponent
if TYPE_CHECKING:
    from ..ai_base import AIBase

class SearchBehavior(AIUnit):

    def __init__(self, ai: AIBase, tag: int):
        super().__init__(ai, tag)

    def search(self) -> Optional[UnitCommand]:

        if self.unit.type_id == UnitTypeId.OVERLORD:
            return None

        if self.unit.is_idle:
            if 1/3 < self.ai.combat.threat_level:
                if target := next((b for b in reversed(self.ai.bases) if b.townhall), None):
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