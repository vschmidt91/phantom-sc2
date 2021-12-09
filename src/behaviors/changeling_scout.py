
from __future__ import annotations
import math

from typing import TYPE_CHECKING
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId

from ..constants import CHANGELINGS
from ..utils import sample
from ..resources.base import Base
from .behavior import Behavior, BehaviorResult, UnitBehavior
if TYPE_CHECKING:
    from ..ai_base import AIBase

class ChangelingScoutBehavior(UnitBehavior):
    
    ABILITY = AbilityId.SPAWNCHANGELING_SPAWNCHANGELING

    def __init__(self, ai: AIBase, unit_tag: int):
        super().__init__(ai, unit_tag)

    def scout_priority(self, base: Base) -> float:
        if base.townhall:
            return 1e-5
        d = self.ai.map_data.distance[base.position.rounded]
        if math.isnan(d) or math.isinf(d):
            return 1e-5
        return d
        
    def execute_single(self, unit: Unit) -> BehaviorResult:

        if unit.type_id in { UnitTypeId.OVERSEER, UnitTypeId.OVERSEERSIEGEMODE }:
            if self.ABILITY not in self.ai.abilities[unit.tag]:
                return BehaviorResult.SUCCESS
            unit(self.ABILITY)
            return BehaviorResult.ONGOING
        elif unit.type_id in CHANGELINGS:
            if unit.is_moving:
                return BehaviorResult.ONGOING
            target = sample(self.ai.bases, key = lambda b : self.scout_priority(b))
            unit.move(target.position)


        return BehaviorResult.SUCCESS