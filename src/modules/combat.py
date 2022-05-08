from __future__ import annotations
from typing import DefaultDict, Optional, Set, Union, Iterable, Tuple, TYPE_CHECKING, List
from enum import Enum
import numpy as np
import random
from sc2.constants import SPEED_INCREASE_ON_CREEP_DICT
from scipy.ndimage import gaussian_filter
import skimage.draw

from sc2.position import Point2
from sc2.unit import Unit
from sc2.unit_command import UnitCommand
from sc2.data import race_worker
from abc import ABC, abstractmethod

from src.units.unit import CommandableUnit, EnemyUnit

from ..value_map import ValueMap
from ..utils import *
from ..constants import *
from ..behaviors.behavior import Behavior
from ..ai_component import AIComponent
from .module import AIModule
if TYPE_CHECKING:
    from ..ai_base import AIBase

class CombatModule(AIModule):
    
    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)
        self.enemy_vs_ground_map: np.ndarray = None
        self.enemy_vs_air_map: np.ndarray = None
        self.army_vs_ground_map: np.ndarray = None
        self.army_vs_air_map: np.ndarray = None
        self.army_projection: np.ndarray = None
        self.enemy_projection: np.ndarray = None
        self.threat_level: float = 0.0

    async def on_step(self):

        enemy_map = ValueMap(self.ai)

        for enemy in self.ai.unit_manager.enemies.values():
            if enemy.unit:
                enemy_map.add(enemy.unit, 0.0)
        self.enemy_vs_ground_map = np.maximum(1, enemy_map.get_map_vs_ground())
        self.enemy_vs_air_map = np.maximum(1, enemy_map.get_map_vs_air())

        # EXPERIMENTAL FIGHTING

        def add_unit_to_map(map: np.ndarray, unit: Unit) -> None:
            radius = unit.radius + max(unit.ground_range, unit.air_range)
            if radius == 0:
                return map
            dps = max(unit.ground_dps, unit.air_dps)
            weight = (unit.health + unit.shield) * dps / (math.pi * radius**2)
            
            disk = skimage.draw.disk(unit.position, radius)
            map[disk] += weight

        def transport(map: np.ndarray, sigma: float) -> np.ndarray:
            return gaussian_filter(map, sigma=sigma)

        army0 = np.zeros(self.ai.game_info.map_size)
        enemy0 = np.zeros(self.ai.game_info.map_size)

        value_army = 0.0
        value_enemy_threats = 0.0

        for unit in self.ai.unit_manager.units.values():
            if (
                isinstance(unit, CombatBehavior)
                and unit.fight_enabled
                and unit.unit
            ):
                value_army += unit.value
                add_unit_to_map(army0, unit.unit)

        for enemy in self.ai.unit_manager.enemies.values():
            if enemy.unit:
                value_enemy_threats += 2 * (1 - self.ai.map_data.distance[enemy.unit.position.rounded]) * enemy.value
                add_unit_to_map(enemy0, enemy.unit)

        movement_speed = 3.5
        t = 3.0
        sigma = movement_speed * t

        army = transport(army0, sigma)
        enemy = transport(enemy0, sigma)

        army_health = np.maximum(0, army - t * enemy)
        enemy_health = np.maximum(0, enemy - t * army)


        # movement_speed = 3.5
        # dt = 0.3
        # for i, t in enumerate(np.arange(0, 3, dt)):

        #     sigma2 = movement_speed * dt
        #     sigma = math.sqrt(sigma2)

        #     army_health = transport(army_health, sigma)
        #     army_dps = transport(army_dps, sigma)
        #     enemy_health = transport(enemy_health, sigma)
        #     enemy_dps = transport(enemy_dps, sigma)

            # army_damage = np.minimum(army_health, enemy_dps * dt)
            # enemy_damage = np.minimum(enemy_health, army_dps * dt)

            # army_health2 = army_health - army_damage
            # enemy_health2 = enemy_health - enemy_damage

            # army_dps *= army_health2 / np.maximum(1, army_health)
            # enemy_dps *= enemy_health2 / np.maximum(1, enemy_health)

            # army_health = army_health2
            # enemy_health = enemy_health2

            # army_losses += army_damage
            # enemy_losses += enemy_damage        

        def orient_image(img: np.ndarray) -> np.ndarray:
            return np.transpose(np.fliplr(img), (1, 0, 2))

        # if self.debug:

        #     health_map = np.stack((enemy_health, army_health, np.zeros_like(army_health)), axis=-1)
        #     dps_map = np.stack((enemy_dps, army_dps, np.zeros_like(army_dps)), axis=-1)
        #     maps = [health_map, dps_map]

        #     if not self.plot_images:
        #         self.plot_images = [self.plot_axes[i].imshow(maps[i]) for i in range(len(maps))]
        #         self.plot_axes[0].set_title("Health")
        #         self.plot_axes[1].set_title("DPS")
        #         plt.show()

        #     for i, data in enumerate(maps):
        #         plot = self.plot_images[i]
        #         plot.set_data(orient_image(data / np.max(data)))
                
        #     self.plot.canvas.flush_events()

        self.army_projection = army
        self.enemy_projection = enemy

        self.threat_level = value_enemy_threats / max(1, value_army + value_enemy_threats)

class CombatStance(Enum):
    FLEE = 1
    RETREAT = 2
    FIGHT = 3
    ADVANCE = 4

class CombatBehavior(CommandableUnit):

    def __init__(self, ai: AIBase, tag: int):
        super().__init__(ai, tag)
        self.fight_enabled: bool = True
        self.fight_stance: CombatStance = CombatStance.FIGHT

    def target_priority(self, target: EnemyUnit) -> float:
        if not target.unit:
            return 0.0
        if not self.ai.can_attack(self.unit, target.unit) and not self.unit.is_detector:
            return 0.0
        if target.unit.is_hallucination:
            return 0.0
        if target.unit.type_id in CHANGELINGS:
            return 0.0
        priority = 1e8

        priority /= 150 + target.unit.position.distance_to(self.ai.start_location)
        priority /= 3 if target.unit.is_structure else 1
        if target.unit.is_enemy:
            priority /= 100 + target.unit.shield + target.unit.health
        else:
            priority /= 500
        priority *= 3 if target.unit.type_id in WORKERS else 1
        priority /= 10 if target.unit.type_id in CIVILIANS else 1

        priority /= 30.0 + target.unit.position.distance_to(self.unit.position)
        if self.unit.is_detector:
            if target.unit.is_cloaked:
                priority *= 10.0
            if not target.unit.is_revealed:
                priority *= 10.0

        return priority


    def get_stance(self, target: Unit) -> CombatStance:

        eps = 1e-3
        army = max(2 * eps, self.ai.combat.army_projection[target.position.rounded])
        enemy = max(eps, self.ai.combat.enemy_projection[self.unit.position.rounded])
        advantage = army / enemy

        if self.unit.ground_range < 2:

            if advantage < 1:
                return CombatStance.FLEE
            else:
                return CombatStance.FIGHT

        else:

            if advantage < 1/2:
                return CombatStance.FLEE
            elif advantage < 1:
                return CombatStance.RETREAT
            elif advantage < 2:
                return CombatStance.FIGHT
            else:
                return CombatStance.ADVANCE

    def get_path_towards(self, target: Point2) -> List[Point2]:
        a = self.ai.game_info.playable_area
        target = Point2(np.clip(target, (a.x, a.y), (a.right, a.top)))
        if self.unit.is_flying:
            enemy_map = self.ai.combat.enemy_vs_air_map
        else:
            enemy_map = self.ai.combat.enemy_vs_ground_map

        path = self.ai.map_analyzer.pathfind(
            start = self.unit.position,
            goal = target,
            grid = enemy_map,
            large = is_large(self.unit),
            smoothing = False,
            sensitivity = 1)

        if not path:
            d = self.unit.distance_to(target)
            return [
                self.unit.position.towards(target, d)
                for i in np.arange(d)
            ]
        return path

    def fight(self) -> Optional[UnitCommand]:

        if not self.fight_enabled:
            return None

        target, priority = max((
                (enemy, self.target_priority(enemy))
                for enemy in self.ai.unit_manager.enemies.values()
            ),
            key = lambda p : p[1],
            default = (None, 0)
        )

        if priority <= 0.0:
            return None

        attack_path = self.get_path_towards(target.unit.position)
        retreat_path = self.get_path_towards(self.unit.position.towards(target.unit.position, -12))

        attack_point = attack_path[min(len(attack_path) - 1, 3)]
        retreat_point = retreat_path[min(len(retreat_path) - 1, 3)]

        # advantage = self.get_advantage(unit, target)
        self.fight_stance = self.get_stance(target.unit)

        if self.fight_stance == CombatStance.FLEE:

            return self.unit.move(retreat_point)

        elif self.fight_stance == CombatStance.RETREAT:

            if (
                (self.unit.weapon_cooldown or self.unit.is_burrowed)
                and self.unit.position.distance_to(target.unit.position) <= self.unit.radius + self.ai.get_unit_range(self.unit) + target.unit.radius + self.unit.distance_to_weapon_ready
            ):
                return self.unit.move(retreat_point)
            elif self.unit.position.distance_to(target.unit.position) <= self.unit.radius + self.ai.get_unit_range(self.unit) + target.unit.radius:
                return self.unit.attack(target.unit)
            else:
                return self.unit.attack(target.unit.position)
            
        elif self.fight_stance == CombatStance.FIGHT:

            if self.unit.position.distance_to(target.unit.position) <= self.unit.radius + self.ai.get_unit_range(self.unit) + target.unit.radius:
                return self.unit.attack(target.unit)
            else:
                return self.unit.attack(attack_point)

        elif self.fight_stance == CombatStance.ADVANCE:

            distance = self.unit.position.distance_to(target.unit.position) - self.unit.radius - target.unit.radius
            if self.unit.weapon_cooldown and 1 < distance:
                return self.unit.move(attack_point)
            elif self.unit.position.distance_to(target.unit.position) <= self.unit.radius + self.ai.get_unit_range(self.unit) + target.unit.radius:
                return self.unit.attack(target.unit)
            else:
                return self.unit.attack(attack_point)