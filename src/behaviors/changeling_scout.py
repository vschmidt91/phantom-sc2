
from __future__ import annotations
import math

from typing import TYPE_CHECKING, Optional
from sc2.unit import Unit
from sc2.unit_command import UnitCommand
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId

from ..constants import ENERGY_COST
from .behavior import Behavior
if TYPE_CHECKING:
    from ..ai_base import AIBase

class SpawnChangeling(Behavior):
    
    ABILITY = AbilityId.SPAWNCHANGELING_SPAWNCHANGELING

    def __init__(self, ai: AIBase, unit_tag: int):
        super().__init__(ai, unit_tag)
        
    def execute_single(self, unit: Unit) -> Optional[UnitCommand]:

        if ENERGY_COST[self.ABILITY] <= unit.energy:
            return unit(self.ABILITY)