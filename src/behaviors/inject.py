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

from src.units.unit import AIUnit

from ..utils import *
from ..constants import *
from .behavior import Behavior
from ..ai_component import AIComponent
if TYPE_CHECKING:
    from ..ai_base import AIBase

class InjectBehavior(AIUnit):
    
    def __init__(self, ai: AIBase, tag: int):
        super().__init__(ai, tag)
        self.did_first_inject: bool = False

    def inject(self) -> Optional[UnitCommand]:

        if not self.did_first_inject:
            townhall = min(
                (th for th in self.ai.townhalls.ready if BuffId.QUEENSPAWNLARVATIMER not in th.buffs),
                key = lambda th : th.position.distance_to(self.unit.position),
                default = None)
            if townhall:
                self.did_first_inject = True
                return self.unit(AbilityId.EFFECT_INJECTLARVA, target=townhall)

        if 1 < self.ai.combat.enemy_vs_ground_map[self.unit.position.rounded]:
            return None

        townhall_tag = self.ai.unit_manager.inject_queens.get(self.unit.tag)
        if not townhall_tag:
            return None

        townhall = self.ai.unit_by_tag.get(townhall_tag)
        if not townhall:
            return None
            
        base = next(b for b in self.ai.bases if b.position == townhall.position)
        if base:
            target = base.position.towards(base.mineral_patches.position, -(townhall.radius + self.unit.radius))
        else:
            target = townhall.position

        if 7 < self.unit.position.distance_to(target):
            return self.unit.attack(target)
        elif ENERGY_COST[AbilityId.EFFECT_INJECTLARVA] <= self.unit.energy:
            return self.unit(AbilityId.EFFECT_INJECTLARVA, target=townhall)
            
        return None