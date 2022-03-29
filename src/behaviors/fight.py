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
        priority /= 30 + target.position.distance_to(unit.position)
        if unit.is_detector:
            priority *= 10 if target.is_cloaked else 1
            priority *= 10 if not target.is_revealed else 1
        return priority

    def get_advantage(self, unit: Unit, target: Unit) -> float:

        if not target:
            return 1
        
        unit_range = unit.radius + self.ai.get_unit_range(unit) + target.radius
        sample_position = unit.position.towards(target.position, unit_range, limit=True)
        
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

    def get_stance(self, unit: Unit, target: Unit) -> FightStance:

        # halfway = .5 * (unit.position + target.position)
        # simulation_result = self.ai.unit_manager.simulation.weighted_result(halfway)

        # if unit.ground_range < 2:

        #     if simulation_result < 1/2:
        #         return FightStance.FLEE
        #     else:
        #         return FightStance.FIGHT

        # else:

        #     if simulation_result < 1/4:
        #         return FightStance.FLEE
        #     elif simulation_result < 2/4:
        #         return FightStance.RETREAT
        #     elif simulation_result < 3/4:
        #         return FightStance.FIGHT
        #     else:
        #         return FightStance.ADVANCE

        if np.sign(self.ai.enemy_projection[target.position.rounded]) <= np.sign(self.ai.army_projection[unit.position.rounded]):
            return FightStance.FIGHT
        else:
            return FightStance.FLEE

    def execute_single(self, unit: Unit) -> BehaviorResult:

        target = self.ai.unit_manager.targets.get(unit.tag)
        
        if not target:
            return BehaviorResult.SUCCESS

        attack_path = self.ai.unit_manager.attack_paths[unit.tag]
        retreat_path = self.ai.unit_manager.retreat_paths[unit.tag]

        attack_point = attack_path[min(len(attack_path) - 1, 3)]
        retreat_point = retreat_path[min(len(retreat_path) - 1, 3)]

        # advantage = self.get_advantage(unit, target)
        self.stance = self.get_stance(unit, target)

        if self.stance == FightStance.FLEE:

            # unit.move(self.get_path_towards(unit, self.ai.start_location))
            unit.move(retreat_point)
            # unit.move(unit.position.towards(target.position, -12))
            return BehaviorResult.ONGOING

        elif self.stance == FightStance.RETREAT:

            if (
                (unit.weapon_cooldown or unit.is_burrowed)
                and unit.position.distance_to(target.position) <= unit.radius + self.ai.get_unit_range(unit) + target.radius + unit.distance_to_weapon_ready
            ):
                # unit.move(unit.position.towards(target.position, -12))
                unit.move(retreat_point)
                # unit.move(self.get_path_towards(unit, self.ai.start_location))
            elif unit.position.distance_to(target.position) <= unit.radius + self.ai.get_unit_range(unit) + target.radius:
                unit.attack(target)
            else:
                unit.attack(target.position)
            return BehaviorResult.ONGOING
            
        elif self.stance == FightStance.FIGHT:

            if unit.position.distance_to(target.position) <= unit.radius + self.ai.get_unit_range(unit) + target.radius:
                unit.attack(target)
            else:
                unit.attack(attack_point)
            return BehaviorResult.ONGOING

        elif self.stance == FightStance.ADVANCE:

            distance = unit.position.distance_to(target.position) - unit.radius - target.radius
            if unit.weapon_cooldown and 1 < distance:
                unit.move(attack_point)
            elif unit.position.distance_to(target.position) <= unit.radius + self.ai.get_unit_range(unit) + target.radius:
                unit.attack(target)
            else:
                unit.attack(attack_point)
            return BehaviorResult.ONGOING

        return BehaviorResult.ONGOING