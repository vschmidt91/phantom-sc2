from __future__ import annotations
from optparse import Option

from typing import Dict, TYPE_CHECKING

from sc2.constants import IS_DETECTOR
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.data import race_townhalls
from sc2.unit_command import UnitCommand

from ..constants import CHANGELINGS
from ..resources.base import Base
from ..behaviors.behavior import Behavior
from ..ai_component import AIComponent
from .module import AIModule
if TYPE_CHECKING:
    from ..ai_base import AIBase
    
class DropManager(AIModule):

    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)
        self.ai: AIBase = ai

        enemy_start = self.ai.enemy_start_locations[0]
        enemy_ramp = min(self.ai.game_info.map_ramps, key = lambda r : r.top_center.distance_to(enemy_start))
        drop_from_priorities = dict()
        for base in self.ai.bases:
            start_distance = base.position.distance_to(enemy_start)
            if start_distance == 0.0:
                continue
            ramp_distance = base.position.distance_to(enemy_ramp.top_center)
            drop_from_priorities[base.position] = ramp_distance - start_distance

        drop_base, priority = max(drop_from_priorities.items(), key = lambda p : p[1])
        self.drop_base = drop_base

        drop_from = None
        drop_to = None
        num_steps = 100
        for i in range(num_steps):
            p = enemy_start + (i / num_steps) * (drop_base - enemy_start)
            if not drop_to:
                if not self.ai.in_pathing_grid(p):
                    drop_to = p
            elif not drop_from:
                if self.ai.in_pathing_grid(p):
                    drop_from = p
                    break

        self.drop_from: Point2 = drop_from or drop_base
        self.drop_to: Point2 = drop_to or enemy_start

    async def on_step(self) -> None:                 
        pass

class DropBehavior(Behavior):

    def __init__(self, ai: AIBase, unit_tag: int):
        super().__init__(ai, unit_tag)
        
    def execute_single(self, unit: Unit) -> Optional[UnitCommand]:

        if unit.type_id == UnitTypeId.OVERLORDTRANSPORT:
            # if len(unit.passengers_tags) < 4:
            #     unit.move(self.ai.drop_manager.drop_from)
            if unit.distance_to(self.ai.drop_manager.drop_to) < 1:
                return unit.move(self.ai.drop_manager.drop_from)
                # unit(AbilityId.UNLOADALL, self.ai.drop_manager.drop_to)
            elif unit.distance_to(self.ai.drop_manager.drop_from) < 1:
                return unit.move(self.ai.drop_manager.drop_to)
            elif unit.is_idle:
                return unit.move(self.ai.drop_manager.drop_from)