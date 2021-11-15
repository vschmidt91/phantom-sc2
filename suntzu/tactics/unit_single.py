
from typing import Optional, Set, Union, Iterable, Tuple
import numpy as np
import random
from sc2.constants import SPEED_INCREASE_ON_CREEP_DICT

from sc2.position import Point2
from sc2.unit import Unit
from abc import ABC, abstractmethod

from ..utils import *
from ..constants import *

class UnitSingle(ABC):

    def __init__(self, tag: int):
        self.tag: int = tag

    def micro(self,
        bot,
        enemies: Iterable[Unit],
        friend_map: np.ndarray,
        enemy_map: np.ndarray,
        enemy_gradient_map: np.ndarray,
        dodge: Iterable[Tuple[Point2, float]] = []
    ):

        unit: Unit = bot.unit_by_tag.get(self.tag)
        if not unit:
            return

        dodge_closest = min(dodge, key = lambda p : unit.distance_to(p[0]) - p[1], default = None)
        if dodge_closest:
            dodge_position, dodge_radius = dodge_closest
            dodge_distance = unit.distance_to(dodge_position) - unit.radius - dodge_radius - 1
            if dodge_distance < 0:
                unit.move(unit.position.towards(dodge_position, dodge_distance))
                return

        def target_priority(target: Unit) -> float:
            if target.is_hallucination:
                return 0
            if target.type_id in CHANGELINGS:
                return 0
            if not canAttack(unit, target) and not unit.is_detector:
                return 0
            priority = 1
            priority *= 10 + target.calculate_dps_vs_target(unit)
            priority /= 100 + target.shield + target.health
            priority /= 10 + unit.position.distance_to(target)
            priority /= 30 + unit.position.distance_to(bot.start_location)
            priority /= 10 if target.is_structure else 1
            if target.type_id in WORKERS:
                priority *= 10
            elif target.type_id in CIVILIANS:
                priority /= 10
            else:
                pass
            priority /= 10 if not target.is_enemy else 1
            if unit.is_detector:
                priority *= 10 if target.is_cloaked else 1
                priority *= 10 if not target.is_revealed else 1
            return priority

        target = max(enemies, key=target_priority, default=None)

        heat_gradient = Point2(bot.distance_gradient_map[unit.position.rounded[0], unit.position.rounded[1],:])
        if 0 < heat_gradient.length:
            heat_gradient = heat_gradient.normalized

        enemy_gradient = Point2(enemy_gradient_map[unit.position.rounded[0], unit.position.rounded[1],:])
        if 0 < enemy_gradient.length:
            enemy_gradient = enemy_gradient.normalized

        gradient = heat_gradient + enemy_gradient
        if 0 < gradient.length:
            gradient = gradient.normalized
        elif target and 0 < unit.distance_to(target):
            gradient = (unit.position - target.position).normalized
        elif 0 < unit.distance_to(bot.start_location):
            gradient = (bot.start_location - unit.position).normalized

        if target and 0 < target_priority(target):

            if target.is_enemy:
                attack_target = target.position
            else:
                attack_target = target

            # friends_rating = sum(unitValue(f) / max(1, target.distance_to(f)) for f in friends)
            # enemies_rating = sum(unitValue(e) / max(1, unit.distance_to(e)) for e in enemies)

            friends_rating = 1 + friend_map[unit.position.rounded]
            enemies_rating = 1 + enemy_map[unit.position.rounded]
            advantage_army = friends_rating / max(1, enemies_rating)

            advantage_defender = 1.5 - bot.distance_map[unit.position.rounded]

            creep_bonus = SPEED_INCREASE_ON_CREEP_DICT.get(unit.type_id, 1)
            if unit.type_id == UnitTypeId.QUEEN:
                creep_bonus = 30
            advantage_creep = 1
            if bot.state.creep.is_empty(unit.position.rounded):
                advantage_creep = 1 / creep_bonus

            advantage = 1
            advantage *= advantage_army
            # advantage *= advantage_defender
            advantage *= advantage_creep
            advantage_threshold = 1

            retreat_target = unit.position - 12 * gradient

            if advantage < advantage_threshold / 2:

                # FLEE
                if not unit.is_moving:
                    unit.move(retreat_target)

            elif advantage < advantage_threshold:

                # RETREAT
                if unit.weapon_cooldown and unit.target_in_range(target, unit.distance_to_weapon_ready):
                    unit.move(retreat_target)
                elif unit.target_in_range(target):
                    unit.attack(target)
                else:
                    unit.attack(attack_target)
                
            elif advantage < advantage_threshold * 2:

                # FIGHT
                if unit.target_in_range(target):
                    unit.attack(target)
                else:
                    unit.attack(attack_target)

            else:

                # PURSUE
                distance = unit.position.distance_to(target.position) - unit.radius - target.radius
                if unit.weapon_cooldown and 1 < distance:
                    unit.move(target.position)
                elif unit.target_in_range(target):
                    unit.attack(target)
                else:
                    unit.attack(attack_target)

        elif not unit.is_attacking:

            if bot.time < 8 * 60:
                target = random.choice(bot.enemy_start_locations)
            else:
                target = random.choice(bot.expansion_locations_list)

            unit.attack(target)