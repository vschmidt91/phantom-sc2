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
from src.resources import base
from src.resources.base import Base
from src.units.structure import Structure

from src.units.unit import CommandableUnit

from ..utils import *
from ..constants import *
from .behavior import Behavior
from ..ai_component import AIComponent
from ..modules.module import AIModule
if TYPE_CHECKING:
    from ..ai_base import AIBase

class InjectManager(AIModule):

    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)

    async def on_step(self) -> None:
        self.assign_queen()

    def assign_queen(self) -> None:

        queens = [
            behavior
            for behavior in self.ai.unit_manager.units.values()
            if isinstance(behavior, InjectBehavior)
        ]
        injected_bases = { q.inject_base for q in queens }

        if unassigned_queen := next(
            (
                queen
                for queen in queens
                if not queen.inject_base
            ),
            None
        ):
            unassigned_queen.inject_base = min(
                (
                    base
                    for base in self.ai.resource_manager.bases
                    if (
                        base.townhall
                        and base not in injected_bases
                        and BuffId.QUEENSPAWNLARVATIMER not in base.townhall.unit.buffs
                    )
                ),
                key = lambda b : b.position.distance_to(unassigned_queen.unit.position),
                default = None
            )

class InjectBehavior(CommandableUnit):
    
    def __init__(self, ai: AIBase, tag: int):
        super().__init__(ai, tag)
        self.inject_base: Optional[Base] = None

    def inject(self) -> Optional[UnitCommand]:

        if not self.inject_base:
            return None

        if not self.inject_base.townhall:
            self.inject_base = None
            return None
            
        target = self.inject_base.position.towards(self.inject_base.mineral_patches.position, -(self.inject_base.townhall.unit.radius + self.unit.radius))

        if 7 < self.unit.position.distance_to(target):
            return self.unit.attack(target)
        elif ENERGY_COST[AbilityId.EFFECT_INJECTLARVA] <= self.unit.energy:
            return self.unit(AbilityId.EFFECT_INJECTLARVA, target=self.inject_base.townhall.unit)
            
        return None