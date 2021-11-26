
from typing import Optional, Set, Union, Iterable, Tuple
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
        priority /= 100 + target.position.distance_to(self.bot.start_location)
        priority /= 3 if target.is_structure else 1

        if target.is_enemy:
            priority /= 100 + target.shield + target.health
        else:
            priority /= 300
        priority *= 3 if target.type_id in WORKERS else 1
        priority /= 10 if target.type_id in CIVILIANS else 1

        if unit.is_detector:
            priority *= 10 if target.is_cloaked else 1
            priority *= 10 if not target.is_revealed else 1
        return priority

    def get_gradient(self, unit: Unit, target: Unit) -> Point2:

        distance_gradient = Point2(self.bot.distance_gradient_map[unit.position.rounded[0], unit.position.rounded[1],:])
        if 0 < distance_gradient.length:
            distance_gradient = distance_gradient.normalized

        enemy_gradient = Point2(self.bot.enemy_gradient_map[unit.position.rounded[0], unit.position.rounded[1],:])
        if 0 < enemy_gradient.length:
            enemy_gradient = enemy_gradient.normalized

        gradient = distance_gradient + enemy_gradient
        if 0 < gradient.length:
            gradient = gradient.normalized
        elif target and 0 < unit.position.distance_to(target.position):
            gradient = (unit.position - target.position).normalized
        elif 0 < unit.position.distance_to(self.bot.start_location):
            gradient = (self.bot.start_location - unit.position).normalized

        return gradient

    def get_advantage(self, unit: Unit) -> float:

        friends_rating = 1 + self.bot.friend_blur_map[unit.position.rounded]
        enemies_rating = 1 + self.bot.enemy_blur_map[unit.position.rounded]
        advantage_army = friends_rating / max(1, enemies_rating)

        creep_bonus = SPEED_INCREASE_ON_CREEP_DICT.get(unit.type_id, 1)
        if unit.type_id == UnitTypeId.QUEEN:
            creep_bonus = 30
        advantage_creep = 1
        if self.bot.state.creep.is_empty(unit.position.rounded):
            advantage_creep = 1 / creep_bonus

        advantage_defender = (1 - self.bot.distance_map[unit.position.rounded]) / max(1e-3, self.bot.power_level)

        advantage = 1
        advantage *= advantage_army
        advantage *= advantage_creep
        advantage *= advantage_defender

        return advantage

    def execute(self, unit: Unit) -> BehaviorResult:

        target, priority = max(
            ((t, self.target_priority(unit, t))
            for t in self.bot.enumerate_enemies()),
            key = lambda p : p[1],
            default = (None, 0)
        )
        
        gradient = self.get_gradient(unit, target)
        retreat_target = unit.position - 12 * gradient
        advantage = self.get_advantage(unit)
        advantage_threshold = 1

        if not target or priority <= 0:
            return BehaviorResult.FAILURE

        if advantage < advantage_threshold / 3:

            # FLEE

            unit.move(retreat_target)
            return BehaviorResult.ONGOING

        elif advantage < advantage_threshold:

            # RETREAT
            if (
                unit.weapon_cooldown
                and unit.position.distance_to(target.position) <= unit.radius + self.bot.get_unit_range(unit) + target.radius + unit.distance_to_weapon_ready
            ):
                unit.move(retreat_target)
            elif unit.position.distance_to(target.position) <= unit.radius + self.bot.get_unit_range(unit) + target.radius:
                unit.attack(target)
            else:
                unit.attack(target.position)
            return BehaviorResult.ONGOING
            
        elif advantage < advantage_threshold * 3:

            # FIGHT
            if unit.position.distance_to(target.position) <= unit.radius + self.bot.get_unit_range(unit) + target.radius:
                unit.attack(target)
            else:
                unit.attack(target.position)
            return BehaviorResult.ONGOING

        else:

            # PURSUE
            distance = unit.position.distance_to(target.position) - unit.radius - target.radius
            if unit.weapon_cooldown and 1 < distance:
                unit.move(target.position)
            elif unit.position.distance_to(target.position) <= unit.radius + self.bot.get_unit_range(unit) + target.radius:
                unit.attack(target)
            else:
                unit.attack(target.position)
            return BehaviorResult.ONGOING