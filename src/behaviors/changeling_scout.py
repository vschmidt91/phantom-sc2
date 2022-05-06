
from __future__ import annotations
import math
from abc import ABC

from typing import TYPE_CHECKING, Optional
from sc2.unit import Unit
from sc2.unit_command import UnitCommand
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId

from ..constants import ENERGY_COST
from .behavior import Behavior
from ..units.unit import AIUnit

if TYPE_CHECKING:
    from ..ai_base import AIBase

class SpawnChangelingBehavior(AIUnit):

    def __init__(self, ai: AIBase, tag: int):
        super().__init__(ai, tag)
        
    def spawn_changeling(self) -> Optional[UnitCommand]:

        if self.unit.type_id in { UnitTypeId.OVERSEER, UnitTypeId.OVERSEERSIEGEMODE }:
            if self.ai.in_pathing_grid(self.unit):
                ability = AbilityId.SPAWNCHANGELING_SPAWNCHANGELING
                if ENERGY_COST[ability] <= self.unit.energy:
                    return self.unit(ability)