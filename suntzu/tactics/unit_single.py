
from typing import Optional, Set, Union, Iterable, Tuple
import numpy as np
import random
from sc2.constants import SPEED_INCREASE_ON_CREEP_DICT

from sc2.position import Point2
from sc2.unit import Unit
from sc2.data import race_worker
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

        elif unit.type_id == UnitTypeId.ROACH:
            if unit.health_percentage < 0.3 and UpgradeId.BURROW in bot.state.upgrades:
                unit(AbilityId.BURROWDOWN)
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
            if not can_attack(unit, target) and not unit.is_detector and not unit.is_burrowed:
                return 0
            priority = 1
            # priority *= 10 + target.calculate_dps_vs_target(unit)
            priority /= 1 + unit.position.distance_to(target)
            priority /= 10 + target.position.distance_to(bot.start_location)
            priority /= 3 if target.is_structure else 1

            if target.is_enemy:
                priority /= 10 + target.shield + target.health
            else:
                priority /= 100
            priority *= 3 if target.type_id in WORKERS else 1
            priority /= 3 if target.type_id in CIVILIANS else 1
            # priority /= 10 if not target.is_enemy else 1

            # priority /= 30 + target.shield + target.health
            # if target.type_id in WORKERS:
            #     priority *= 3
            # elif target.type_id in CIVILIANS:
            #     priority /= 3
            # else:
            #     pass
            # priority /= 3 if not target.is_enemy else 1

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

        gradient = enemy_gradient
        if 0 < gradient.length:
            gradient = gradient.normalized
        elif target and 0 < unit.distance_to(target):
            gradient = (unit.position - target.position).normalized
        elif 0 < unit.distance_to(bot.start_location):
            gradient = (bot.start_location - unit.position).normalized
        retreat_target = unit.position - 12 * gradient

        friends_rating = 1 + friend_map[unit.position.rounded]
        enemies_rating = 1 + enemy_map[unit.position.rounded]
        advantage_army = friends_rating / max(1, enemies_rating)

        creep_bonus = SPEED_INCREASE_ON_CREEP_DICT.get(unit.type_id, 1)
        if unit.type_id == UnitTypeId.QUEEN:
            creep_bonus = 10
        advantage_creep = 1
        if bot.state.creep.is_empty(unit.position.rounded):
            advantage_creep = 1 / creep_bonus

        advantage = 1
        advantage *= advantage_army
        advantage *= advantage_creep
        advantage_threshold = 1 - len(bot.drafted_civilians) / max(1, bot.count(race_worker[bot.race]))


        if target and 0 < target_priority(target):

            if target.is_enemy:
                attack_target = target.position
            else:
                attack_target = target

            if advantage < advantage_threshold / 3:

                # FLEE

                unit.move(retreat_target)

            elif unit.is_burrowed:
                if unit.health_percentage == 1:
                    unit(AbilityId.BURROWUP)

            elif advantage < advantage_threshold:

                # RETREAT
                if unit.weapon_cooldown and unit.target_in_range(target, unit.distance_to_weapon_ready):
                    unit.move(retreat_target)
                else:
                    unit.stop()
                # elif unit.target_in_range(target):
                #     unit.attack(target)
                # else:
                #     unit.attack(attack_target)
                
            elif advantage < advantage_threshold * 3:

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