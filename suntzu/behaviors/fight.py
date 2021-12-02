
from typing import DefaultDict, Optional, Set, Union, Iterable, Tuple
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
from .behavior import Behavior, BehaviorResult

class FightStance(Enum):
    FLEE = 1
    RETREAT = 2
    FIGHT = 3
    ADVANCE = 4

class FightBehavior(Behavior):

    def __init__(self, bot):
        self.bot = bot

    def target_priority(self, unit: Unit, target: Unit) -> float:
        if target.is_hallucination:
            return 0
        if target.type_id in CHANGELINGS:
            return 0
        if not self.bot.can_attack(unit, target) and not unit.is_detector:
            return 0
        priority = 1e5
        # priority *= 10 + target.calculate_dps_vs_target(unit)
        priority /= 30 + target.position.distance_to(unit.position)
        priority /= 150 + target.position.distance_to(self.bot.start_location)
        priority /= 3 if target.is_structure else 1

        if target.is_enemy:
            priority /= 100 + target.shield + target.health
        else:
            priority /= 100
        priority *= 3 if target.type_id in WORKERS else 1
        priority /= 10 if target.type_id in CIVILIANS else 1

        if unit.is_detector:
            priority *= 10 if target.is_cloaked else 1
            priority *= 10 if not target.is_revealed else 1
        return priority

    def get_advantage(self, unit: Unit, target: Unit) -> float:

        if not target:
            return 1

        # unit_range = self.bot.get_unit_range(unit)
        # target_range = self.bot.get_unit_range(target)
        # range_ratio = target_range / max(1, unit_range + target_range)
        range_ratio = 0.5
        sample_offset = range_ratio * (target.position - unit.position)
        # if unit_range < sample_offset.length:
        #     sample_offset = unit_range * sample_offset.normalized
        sample_position = unit.position + sample_offset
        friends_rating = self.bot.army_influence_map[sample_position.rounded]
        enemies_rating = self.bot.enemy_influence_map[sample_position.rounded]

        advantage_army = friends_rating / max(1, enemies_rating)

        creep_bonus = SPEED_INCREASE_ON_CREEP_DICT.get(unit.type_id, 1)
        if unit.type_id == UnitTypeId.QUEEN:
            creep_bonus = 30
        advantage_creep = 1
        if self.bot.state.creep.is_empty(unit.position.rounded):
            advantage_creep = 1 / creep_bonus

        # advantage_defender = (1 - self.bot.distance_map[unit.position.rounded]) / max(1e-3, self.bot.power_level)
        advantage_defender = 1 + .2 / self.bot.distance_map[unit.position.rounded]

        advantage = 1
        advantage *= advantage_army
        advantage *= advantage_creep
        advantage *= max(1, advantage_defender)

        return advantage

    def get_path_towards(self, start: Point2, target: Point2) -> Point2:
        retreat_path = self.bot.map_analyzer.pathfind(
            start = start,
            goal = target,
            grid = self.bot.enemy_influence_map,
            large = False,
            smoothing = False,
            sensitivity = 1)

        if retreat_path and 2 <= len(retreat_path):
            retreat_target = retreat_path[1]
        else:
            retreat_target = start
        return retreat_target

    def get_stance(self, unit: Unit, advantage: float) -> FightStance:
        if self.bot.get_unit_range(unit) < 2:
            if advantage < 1:
                return FightStance.FLEE
            else:
                return FightStance.FIGHT
        else:
            if advantage < 1/3:
                return FightStance.FLEE
            elif advantage < 1:
                return FightStance.RETREAT
            elif advantage < 3:
                return FightStance.FIGHT
            else:
                return FightStance.ADVANCE

    def execute(self, unit: Unit) -> BehaviorResult:

        target, priority = max(
            ((t, self.target_priority(unit, t))
            for t in self.bot.enumerate_enemies()),
            key = lambda p : p[1],
            default = (None, 0)
        )

        if priority <= 0:
            return BehaviorResult.FAILURE

        advantage = self.get_advantage(unit, target)
        stance = self.get_stance(unit, advantage)

        if stance == FightStance.FLEE:

            unit.move(self.get_path_towards(unit.position, self.bot.start_location))
            return BehaviorResult.ONGOING

        elif stance == FightStance.RETREAT:

            if (
                (unit.weapon_cooldown or unit.is_burrowed)
                and unit.position.distance_to(target.position) <= unit.radius + self.bot.get_unit_range(unit) + target.radius + unit.distance_to_weapon_ready
            ):
                unit.move(self.get_path_towards(unit.position, self.bot.start_location))
            elif unit.position.distance_to(target.position) <= unit.radius + self.bot.get_unit_range(unit) + target.radius:
                unit.attack(target)
            else:
                unit.attack(target.position)
            return BehaviorResult.ONGOING
            
        elif stance == FightStance.FIGHT:

            if unit.position.distance_to(target.position) <= unit.radius + self.bot.get_unit_range(unit) + target.radius:
                unit.attack(target)
            else:
                unit.attack(self.get_path_towards(unit.position, target.position))
            return BehaviorResult.ONGOING

        elif stance == FightStance.ADVANCE:

            distance = unit.position.distance_to(target.position) - unit.radius - target.radius
            if unit.weapon_cooldown and 1 < distance:
                unit.move(self.get_path_towards(unit.position, target.position))
            elif unit.position.distance_to(target.position) <= unit.radius + self.bot.get_unit_range(unit) + target.radius:
                unit.attack(target)
            else:
                unit.attack(self.get_path_towards(unit.position, target.position))
            return BehaviorResult.ONGOING

        return BehaviorResult.FAILURE