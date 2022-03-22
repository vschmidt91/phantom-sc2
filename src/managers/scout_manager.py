from __future__ import annotations
import math

from typing import Dict, List, TYPE_CHECKING
from sc2.constants import IS_DETECTOR
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2

from ..constants import CHANGELINGS
from ..resources.base import Base
from ..behaviors.behavior import Behavior, BehaviorResult, UnitBehavior
from ..ai_component import AIComponent

if TYPE_CHECKING:
    from ..ai_base import AIBase
    
class ScoutManager(AIComponent, Behavior):

    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)
        self.scouts: Dict[Point2, int] = dict()
        self.scout_enemy_natural: bool = True

        self.static_targets: List[Point2] = list()
        for base in self.ai.bases[1:len(self.ai.bases)//2]:
            self.static_targets.append(base.position)

        ramps = sorted(self.ai.game_info.map_ramps, key=lambda r:r.bottom_center.distance_to(self.ai.start_location))
        for ramp in ramps[:len(ramps)//2]:
            self.static_targets.append(ramp.bottom_center.towards(self.ai.game_info.map_center, 10))

        self.static_targets.sort(key=lambda t:t.distance_to(self.ai.start_location))

    def execute(self) -> BehaviorResult:

        targets = list(self.static_targets)
        if self.scout_enemy_natural and self.ai.block_manager.enemy_base_count < 2:
            target = self.ai.bases[-2].position.towards(self.ai.game_info.map_center, 11)
            targets.insert(0, target)

        for target in targets:

            if target in self.scouts:
                continue
            
            overlord = next(
                (o
                for o in self.ai.actual_by_type[UnitTypeId.OVERLORD]
                if o.tag not in self.scouts.values()
            ), None)
            if not overlord:
                break
            self.scouts[target] = overlord.tag

        for pos, tag in list(self.scouts.items()):
            if pos not in targets:
                del self.scouts[pos]
            elif tag not in self.ai.unit_by_tag:
                del self.scouts[pos]
                    
        return BehaviorResult.SUCCESS

class ScoutBehavior(UnitBehavior):
    
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

        target = next((
            pos
            for pos, tag in self.ai.scout_manager.scouts.items()
            if tag == unit.tag
            ), None)

        if not target:
            return BehaviorResult.SUCCESS

        if unit.position.distance_to(target) < 1:
            return BehaviorResult.SUCCESS

        if unit.is_moving and target.distance_to(unit.order_target) < 1:
            return BehaviorResult.ONGOING

        unit.move(target)
        return BehaviorResult.ONGOING