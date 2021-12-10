from __future__ import annotations
import math

from typing import Dict, TYPE_CHECKING
from sc2.constants import IS_DETECTOR
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.data import race_townhalls

from ..constants import CHANGELINGS
from ..resources.base import Base
from .behavior import Behavior, BehaviorResult, UnitBehavior
if TYPE_CHECKING:
    from ..ai_base import AIBase
    
class BlockManager(Behavior):

    def __init__(self, ai: AIBase) -> None:
        super().__init__()
        self.ai: AIBase = ai
        self.detectors: Dict[Point2, int] = dict()
        self.enemy_base_count: int = 1

    def reset_blocked_bases(self):
        for base in self.ai.bases:
            if base.blocked_since:
                if base.blocked_since + 30 < self.ai.time:
                    base.blocked_since = None

    def execute(self) -> BehaviorResult:

        self.reset_blocked_bases()

        detectors = [
            u
            for t in IS_DETECTOR
            for u in self.ai.actual_by_type[t]
            if 0 < u.movement_speed
        ]
        for base in self.ai.bases:
            if base.blocked_since:
                detector_tag = self.detectors.get(base.position)
                detector = self.ai.unit_by_tag.get(detector_tag)
                if not detector:
                    detector = min(
                        (d for d in detectors if d.tag not in self.detectors.values()),
                        key = lambda u : u.position.distance_to(base.position),
                        default = None)
                    if not detector:
                        continue
                    self.detectors[base.position] = detector.tag
            else:
                if base.position in self.detectors:
                    del self.detectors[base.position]

        for pos, tag in list(self.detectors.items()):
            if tag in self.ai.unit_by_tag:
                continue
            del self.detectors[pos]

        enemy_townhall_positions = {
            th.position
            for t in race_townhalls[self.ai.enemy_race]
            for th in self.ai.enemies_by_type[t]
        }

        for base in self.ai.bases:
            if self.ai.is_visible(base.position):
                if base.position in enemy_townhall_positions:
                    base.taken_since = self.ai.time
                else:
                    base.taken_since = None
        self.enemy_base_count = sum(1 for b in self.ai.bases if b.taken_since and not b.townhall)
        self.enemy_base_count = max(math.ceil(self.ai.time / (4 * 60)), self.enemy_base_count)
                    
        return BehaviorResult.SUCCESS

class DetectBehavior(UnitBehavior):

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

        base_position = next((
            pos
            for pos, tag in self.ai.block_manager.detectors.items()
            if tag == unit.tag
            ), None)

        if not base_position:
            return BehaviorResult.SUCCESS

        target_distance = unit.detect_range - 3
        if target_distance < unit.position.distance_to(base_position):
            unit.move(base_position.towards(unit, target_distance))

        return BehaviorResult.ONGOING