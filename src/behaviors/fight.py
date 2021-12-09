from __future__ import annotations
from typing import DefaultDict, Optional, Set, Union, Iterable, Tuple, TYPE_CHECKING
from enum import Enum
import numpy as np
import random
from sc2.constants import SPEED_INCREASE_ON_CREEP_DICT

from sc2.position import Point2
from sc2.unit import Unit
from sc2.unit_command import UnitCommand
from sc2.data import race_worker
from abc import ABC, abstractmethod

from ..utils import *
from ..constants import *
from .behavior import Behavior, BehaviorResult, UnitBehavior
from ..ai_component import AIComponent
if TYPE_CHECKING:
    from ..ai_base import AIBase

class FightStance(Enum):
    FLEE = 1
    RETREAT = 2
    FIGHT = 3
    ADVANCE = 4

class FightBehavior(UnitBehavior):

    def __init__(self, ai: AIBase, unit_tag: int):
        super().__init__(ai, unit_tag)
        self.stance: FightStance = FightStance.FIGHT

    def target_priority(self, unit: Unit, target: Unit) -> float:
        if not self.ai.can_attack(unit, target) and not unit.is_detector:
            return 0
        priority = self.ai.unit_manager.enemy_priorities[target.tag]
        priority /= 50 + target.position.distance_to(unit.position)
        if unit.is_detector:
            priority *= 10 if target.is_cloaked else 1
            priority *= 10 if not target.is_revealed else 1
        return priority

    def get_advantage(self, unit: Unit, target: Unit) -> float:

        if not target:
            return 1
        
        unit_range = unit.radius + self.ai.get_unit_range(unit) + target.radius
        sample_position = unit.position.towards(target.position, unit_range, limit=True)
        
        # friends_rating = self.ai.army_influence_map[sample_position.rounded]
        # enemies_rating = self.ai.enemy_influence_map[sample_position.rounded]
        
        # advantage_army = friends_rating / max(1, enemies_rating)
        # advantage_defender = (1 - self.ai.distance_map[unit.position.rounded]) / max(1e-3, self.ai.power_level)

        if unit.type_id == UnitTypeId.QUEEN:
            creep_bonus = 30
        else:
            creep_bonus = SPEED_INCREASE_ON_CREEP_DICT.get(unit.type_id, 1)

        advantage_creep = 1
        if self.ai.state.creep.is_empty(unit.position.rounded):
            advantage_creep = 1 / creep_bonus
        else:
            advantage_creep = 1

        # advantage_defender = .5 / self.ai.distance_map[unit.position.rounded]

        advantage = self.ai.advantage_map[sample_position.rounded]
        # advantage *= advantage_army
        # advantage *= max(1, advantage_defender)
        advantage *= advantage_creep

        return advantage

    def get_path_towards(self, unit: Unit, target: Point2) -> Point2:
        path = self.ai.map_analyzer.pathfind(
            start = unit.position,
            goal = target,
            grid = self.ai.enemy_influence_map,
            large = is_large(unit),
            smoothing = False,
            sensitivity = 1)

        if not path:
            return target.position
        return path[min(3, len(path) - 1)]

    def get_stance(self, unit: Unit, advantage: float) -> FightStance:
        if self.ai.get_unit_range(unit) < 2:
            if self.stance is FightStance.FLEE:
                if advantage < 3/2:
                    return FightStance.FLEE
                else:
                    return FightStance.FIGHT
            elif self.stance is FightStance.FIGHT:
                if advantage < 2/3:
                    return FightStance.FLEE
                else:
                    return FightStance.FIGHT
        else:
            if advantage < 2/3:
                return FightStance.FLEE
            elif advantage < 3/2:
                return FightStance.RETREAT
            elif advantage < 3:
                return FightStance.FIGHT
            else:
                return FightStance.ADVANCE

    def execute_single(self, unit: Unit) -> BehaviorResult:

        if unit.type_id == UnitTypeId.OVERLORD:
            return BehaviorResult.SUCCESS

        target, priority = max(
            ((t, self.target_priority(unit, t))
            for t in self.ai.enumerate_enemies()),
            key = lambda p : p[1],
            default = (None, 0)
        )

        if priority <= 0:
            return BehaviorResult.SUCCESS

        advantage = self.get_advantage(unit, target)
        self.stance = self.get_stance(unit, advantage)

        if self.stance == FightStance.FLEE:

            unit.move(self.get_path_towards(unit, self.ai.start_location))
            return BehaviorResult.ONGOING

        elif self.stance == FightStance.RETREAT:

            if (
                (unit.weapon_cooldown or unit.is_burrowed)
                and unit.position.distance_to(target.position) <= unit.radius + self.ai.get_unit_range(unit) + target.radius + unit.distance_to_weapon_ready
            ):
                unit.move(self.get_path_towards(unit, self.ai.start_location))
            elif unit.position.distance_to(target.position) <= unit.radius + self.ai.get_unit_range(unit) + target.radius:
                unit.attack(target)
            else:
                unit.attack(target.position)
            return BehaviorResult.ONGOING
            
        elif self.stance == FightStance.FIGHT:

            if unit.position.distance_to(target.position) <= unit.radius + self.ai.get_unit_range(unit) + target.radius:
                unit.attack(target)
            else:
                unit.attack(self.get_path_towards(unit, target.position))
            return BehaviorResult.ONGOING

        elif self.stance == FightStance.ADVANCE:

            distance = unit.position.distance_to(target.position) - unit.radius - target.radius
            if unit.weapon_cooldown and 1 < distance:
                unit.move(self.get_path_towards(unit, target.position))
            elif unit.position.distance_to(target.position) <= unit.radius + self.ai.get_unit_range(unit) + target.radius:
                unit.attack(target)
            else:
                unit.attack(self.get_path_towards(unit, target.position))
            return BehaviorResult.ONGOING

        return BehaviorResult.SUCCESS