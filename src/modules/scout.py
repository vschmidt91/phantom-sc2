from __future__ import annotations
import math

from typing import Dict, List, TYPE_CHECKING, Optional, Iterable
from sc2.constants import IS_DETECTOR
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.unit_command import UnitCommand
from src.units.unit import CommandableUnit

from ..constants import CHANGELINGS
from ..resources.base import Base
from ..behaviors.behavior import Behavior
from .module import AIModule

if TYPE_CHECKING:
    from ..ai_base import AIBase
    
class ScoutModule(AIModule):

    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)

        self.scout_enemy_natural: bool = True
        self.blocked_positions: Dict[Point2, float] = dict()
        self.enemy_bases: Dict[Point2, float] = dict()
        self.static_targets: List[Point2] = list()

        for base in self.ai.resource_manager.bases[1:len(self.ai.resource_manager.bases)//2]:
            self.static_targets.append(base.position)
            
        self.static_targets.sort(key=lambda t:t.distance_to(self.ai.start_location))

        for pos in self.ai.enemy_start_locations:
            self.enemy_bases[pos] = 0
            if path := self.ai.map_analyzer.pathfind(self.ai.start_location, pos):
                self.static_targets.insert(1, path[len(path) // 2])

    def reset_blocked_bases(self) -> None:
        for position, blocked_since in list(self.blocked_positions.items()):
            if blocked_since + 60 < self.ai.time:
                del self.blocked_positions[position]

    def find_taken_bases(self) -> None:

        enemy_building_positions = {
            enemy.unit.position
            for enemy in self.ai.unit_manager.enemies.values()
            if enemy.unit and enemy.unit.is_structure
        }

        for base in self.ai.resource_manager.bases:
            if self.ai.is_visible(base.position):
                if base.position in enemy_building_positions:
                    if base.position not in self.enemy_bases:
                        self.enemy_bases[base.position] = self.ai.time
                else:
                    if base.position in self.enemy_bases:
                        del self.enemy_bases[base.position]

    def send_units(self, units: List[ScoutBehavior], targets: List[Point2]) -> None:

        targets_set = set(targets)
        for scout in units:
            if scout.scout_position not in targets_set:
                scout.scout_position = None

        scouted_positions = { scout.scout_position for scout in units }
        if (
            (unscouted_target := next((t for t in targets if t not in scouted_positions), None))
            and (scout := next((s for s in units if not s.scout_position), None))
        ):
            scout.scout_position = unscouted_target


    async def on_step(self) -> None:

        scouts = [
            behavior
            for behavior in self.ai.unit_manager.units.values()
            if isinstance(behavior, ScoutBehavior)
        ]
        detectors = [
            behavior
            for behavior in scouts
            if behavior.unit.is_detector
        ]
        nondetectors = [
            behavior
            for behavior in scouts
            if not behavior.unit.is_detector
        ]
        scout_targets = []
        if self.scout_enemy_natural and len(self.enemy_bases) < 2:
            target = self.ai.resource_manager.bases[-2].position.towards(self.ai.game_info.map_center, 11)
            scout_targets.append(target)
        scout_targets.extend(self.static_targets)

        self.reset_blocked_bases()
        self.find_taken_bases()
        self.send_units(detectors, self.blocked_positions.keys())
        self.send_units(nondetectors, scout_targets)

class ScoutBehavior(CommandableUnit):
    
    def __init__(self, ai: AIBase, tag: int):
        super().__init__(ai, tag)
        self.scout_position: Optional[Point2] = None
        
    def scout(self) -> Optional[UnitCommand]:

        if self.scout_position:
            if self.scout_position.distance_to(self.unit) < self.unit.radius + self.unit.sight_range:
                return self.unit.hold_position()
            else:
                return self.unit.move(self.scout_position)
        else:
            return None