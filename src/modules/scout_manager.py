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
from .module import AIModule

if TYPE_CHECKING:
    from ..ai_base import AIBase
    
class ScoutManager(AIModule):

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
        self.static_targets.insert(1, self.ai.game_info.map_center)

        self.detectors: Dict[Point2, int] = dict()
        self.blocked_positions: Dict[Point2, float] = dict()
        self.enemy_bases: Dict[Point2, float] = dict()
        
        for pos in self.ai.enemy_start_locations:
            self.enemy_bases[pos] = 0

    def reset_blocked_bases(self) -> None:
        for position, blocked_since in list(self.blocked_positions.items()):
            if blocked_since + 60 < self.ai.time:
                del self.blocked_positions[position]

    def find_taken_bases(self) -> None:

        enemy_building_positions = {
            building.position
            for building in self.ai.enemies.values()
            if building.is_structure
        }

        for base in self.ai.bases:
            if self.ai.is_visible(base.position):
                if base.position in enemy_building_positions:
                    if base.position not in self.enemy_bases:
                        self.enemy_bases[base.position] = self.ai.time
                else:
                    if base.position in self.enemy_bases:
                        del self.enemy_bases[base.position]

    def send_detectors(self) -> None:
        
        detectors = [
            u
            for t in IS_DETECTOR
            for u in self.ai.actual_by_type[t]
            if 0 < u.movement_speed
        ]
        for position in self.blocked_positions.keys():
            detector_tag = self.detectors.get(position)
            detector = self.ai.unit_by_tag.get(detector_tag)
            if not detector:
                detector = min(
                    (d for d in detectors if d.tag not in self.detectors.values()),
                    key = lambda u : u.position.distance_to(position),
                    default = None)
                if not detector:
                    continue
                self.detectors[position] = detector.tag

        for pos, tag in list(self.detectors.items()):
            if tag not in self.ai.unit_by_tag:
                del self.detectors[pos]
            if pos not in self.blocked_positions:
                del self.detectors[pos]

    def send_scouts(self) -> None:

        targets = list(self.static_targets)
        if self.scout_enemy_natural and len(self.enemy_bases) < 2:
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

    async def on_step(self) -> None:
        self.reset_blocked_bases()
        self.find_taken_bases()
        self.send_detectors()
        self.send_scouts()

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
            for pos, tag in self.ai.scout_manager.detectors.items()
            if tag == unit.tag
            ), None)

        if not base_position:
            return BehaviorResult.SUCCESS

        target_distance = unit.detect_range - 3
        if target_distance < unit.position.distance_to(base_position):
            unit.move(base_position.towards(unit, target_distance))

        return BehaviorResult.ONGOING