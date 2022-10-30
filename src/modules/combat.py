from __future__ import annotations
from dataclasses import dataclass
from os import truncate
from random import gauss
import copy

from sklearn.cluster import DBSCAN, KMeans
from enum import Enum, auto
from itertools import chain
from typing import TYPE_CHECKING, List, Optional, Iterable, Set, Dict, Union
import numpy as np
from scipy.spatial.distance import cdist
import math

from scipy.ndimage.filters import gaussian_filter
from scipy.cluster.vq import kmeans
from skimage.draw import disk
from skimage.transform import resize, rescale

from src.behaviors.bile import BileBehavior
from src.cost import Cost

from ..utils import center
from ..influence_map import InfluenceMap

from sc2.unit import UnitCommand, Unit, Point2
from sc2.ids.unit_typeid import UnitTypeId
from sc2.units import Units

from ..units.unit import AIUnit
# from ..units.worker import Worker
from .module import AIModule
from ..constants import WORKERS, CIVILIANS, CHANGELINGS

if TYPE_CHECKING:
    from ..ai_base import AIBase
    from ..units.unit import Worker

class Enemy:

    def __init__(self, unit: Unit) -> None:
        self.unit = unit
        self.targets: List[CombatBehavior] = []
        self.threats: List[CombatBehavior] = []
        self.dps_incoming: float = 0.0
        self.estimated_surival: float = np.inf


class CombatStance(Enum):
    FLEE = auto()
    RETREAT = auto()
    FIGHT = auto()
    ADVANCE = auto()

class InfluenceMapEntry(Enum):
    DPS_GROUND_GROUND = 0
    DPS_GROUND_AIR = 1
    DPS_AIR_GROUND = 2
    DPS_AIR_AIR = 3
    HP_GROUND = 4
    HP_AIR = 5
    COUNT = 6

CONFIDENCE_MAP_SCALE = 6

class CombatModule(AIModule):

    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)
        self.confidence: float = 1.0
        self.ground_dps = np.zeros((self.ai.game_info.map_size))
        self.air_dps = np.zeros((self.ai.game_info.map_size))
        self.army_map: InfluenceMap = InfluenceMap.zeros([*self.ai.game_info.map_size, 7])
        self.enemy_map: InfluenceMap = InfluenceMap.zeros([*self.ai.game_info.map_size, 7])
        self.army: List[CombatBehavior] = []
        self.enemies: Dict[int, Enemy] = {}

    def target_priority(self, target: Unit) -> float:
        if target.is_hallucination:
            return 0.0
        if target.type_id in CHANGELINGS:
            return 0.0
        priority = 1e8

        priority /= 2 + self.ai.distance_ground[target.position.rounded]
        priority /= 3 if target.is_structure else 1
        if target.is_enemy:
            priority /= 100 + target.shield + target.health
        else:
            priority /= 500
        # priority *= 3 if target.type_id in WORKERS else 1
        # priority /= 10 if target.type_id in CIVILIANS else 1

        return priority

    async def on_step(self):

        self.army = [
            behavior
            for behavior in self.ai.unit_manager.units.values()
            if (
                isinstance(behavior, CombatBehavior)
                # and (
                #     behavior.unit.type_id not in CIVILIANS
                #     or (hasattr(behavior, 'is_drafted') and behavior.is_drafted)
                # )
            )
        ]

        self.enemies = {
            unit.tag: Enemy(unit)
            for unit in self.ai.unit_manager.enemies.values()
            if (unit.type_id not in CIVILIANS or self.ai.time < 120)
        }

        def time_until_in_range(unit: Unit, target: Unit) -> float:
            if target.is_flying:
                r = unit.air_range
            else:
                r = unit.ground_range
            d = np.linalg.norm(unit.position - target.position)
            d =d - unit.radius - target.radius - r
            return d / max(1, unit.movement_speed)

        for behavior in self.army:
            behavior.targets.clear()
            behavior.threats.clear()
            unit = behavior.unit
            for enemy_behavior in self.enemies.values():
                enemy = enemy_behavior.unit
                if (
                    self.ai.can_attack(unit, enemy)
                    and time_until_in_range(unit, enemy) < 3
                ):
                    behavior.targets.append(enemy_behavior)
                    enemy_behavior.threats.append(behavior)
                if (
                    self.ai.can_attack(enemy, unit)
                    and time_until_in_range(enemy, unit) < 3
                ):
                    enemy_behavior.targets.append(behavior)
                    behavior.threats.append(enemy_behavior)

        def dps(unit: Unit) -> float:
            return max(unit.air_dps, unit.ground_dps)

        for behavior in chain(self.army, self.enemies.values()):
            unit = behavior.unit
            behavior.dps_incoming = sum(
               dps(e.unit) / len(e.targets)
               for e in behavior.threats
            )
            if 0 < behavior.dps_incoming:
                behavior.estimated_surival = (unit.health + unit.shield) / behavior.dps_incoming
            else:
                behavior.estimated_surival = np.inf

        self.target_priority_dict = {
            unit.tag: self.target_priority(unit)
            for unit in self.ai.unit_manager.enemies.values()
        }

        def dps_entry(unit: Unit):
            if unit.is_flying:
                value = (
                    0.0,
                    0.0,
                    unit.ground_dps,
                    unit.air_dps,
                    0.0,
                    0.0,
                    0.0,
                )
                radius = unit.radius + unit.air_range + 1
            else:
                value = (
                    unit.ground_dps,
                    unit.air_dps,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                )
                radius = unit.radius + unit.ground_range + 1
            return value, radius + unit.movement_speed

        def hp_entry(unit: Unit):
            if unit.is_flying:
                value = (
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    unit.health + unit.shield,
                    1,
                )
                radius = unit.radius
            else:
                value = (
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    unit.health + unit.shield,
                    0.0,
                    1,
                )
                radius = unit.radius
            return value, radius + unit.movement_speed

        self.army_map.clear()
        for behavior in self.army:
            unit = behavior.unit
            value, radius = dps_entry(unit)
            self.army_map.add(unit.position, radius, value)
            value, radius = hp_entry(unit)
            self.army_map.add(unit.position, radius, value)

        self.enemy_map.clear()
        for behavior in self.enemies.values():
            unit = behavior.unit
            value, radius = dps_entry(unit)
            self.enemy_map.add(unit.position, radius, value)
            value, radius = hp_entry(unit)
            self.enemy_map.add(unit.position, radius, value)

        self.army_map.blur(5)
        self.enemy_map.blur(5)

        def unit_value(cost: Cost):
            return cost.minerals + cost.vespene

        army_cost = sum(
            unit_value(self.ai.unit_cost[behavior.unit.type_id])
            for behavior in self.army
        )
        enemy_cost = sum(
            unit_value(self.ai.unit_cost[behavior.unit.type_id])
            for behavior in self.enemies.values()
        )
        self.confidence = army_cost / max(1, army_cost + enemy_cost)

        # retreat_ground = 2 - self.confidence_map
        retreat_ground = 1 + self.enemy_map.data[:, :, InfluenceMapEntry.DPS_GROUND_GROUND.value] + self.enemy_map.data[:, :, InfluenceMapEntry.DPS_AIR_GROUND.value]
        # retreat_ground = blur(retreat_ground)
        # retreat_ground = retreat_ground * self.ai.distance_ground
        retreat_ground = np.stack(np.gradient(retreat_ground))
        self.retreat_ground = retreat_ground

        # retreat_air = 2 - self.confidence_map
        retreat_air = 1 + self.enemy_map.data[:, :, InfluenceMapEntry.DPS_GROUND_AIR.value] + self.enemy_map.data[:, :, InfluenceMapEntry.DPS_AIR_AIR.value]
        # retreat_air = blur(retreat_air)
        # retreat_air = retreat_air * self.ai.distance_air
        retreat_air = np.stack(np.gradient(retreat_air))
        self.retreat_air = retreat_air
            


class CombatBehavior(AIUnit):

    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)
        self.stance: CombatStance = CombatStance.FIGHT
        self.targets: List[Enemy] = []
        self.threats: List[Enemy] = []
        self.dps_incoming: float = 0.0
        self.estimated_surival: float = np.inf

    def target_priority(self, target: Unit) -> float:
        if not (
            self.ai.can_attack(self.unit, target) 
            or self.unit.is_detector
            # or self.unit.is_burrowed
        ):
            return 0.0
        priority = 1e8
        priority /= 30.0 + target.position.distance_to(self.unit.position)
        if self.unit.is_detector:
            if target.is_cloaked:
                priority *= 10.0
            if not target.is_revealed:
                priority *= 10.0

        return priority

    def fight(self) -> Optional[UnitCommand]:

        target, priority = max(
            (
                (enemy, self.target_priority(enemy) * self.ai.combat.target_priority_dict.get(enemy.tag, 0))
                for enemy in self.ai.unit_manager.enemies.values()
            ),
            key = lambda p : p[1],
            default = (None, 0)
        )

        if not target:
            return None
        if priority <= 0:
            return None

        # target_point = self.unit.position.towards(target, 24, limit=True)
        # army_entry = self.ai.combat.army_map[target_point]
        # enemy_entry = self.ai.combat.enemy_map[self.unit.position]
        # if self.unit.is_flying:
        #     enemy_dps = enemy_entry[InfluenceMapEntry.DPS_GROUND_AIR.value] + enemy_entry[InfluenceMapEntry.DPS_AIR_AIR.value]
        # else:
        #     enemy_dps = enemy_entry[InfluenceMapEntry.DPS_GROUND_GROUND.value] + enemy_entry[InfluenceMapEntry.DPS_AIR_GROUND.value]

        # if target.is_flying:
        #     army_dps = army_entry[InfluenceMapEntry.DPS_GROUND_AIR.value] + army_entry[InfluenceMapEntry.DPS_AIR_AIR.value]
        # else:
        #     army_dps = army_entry[InfluenceMapEntry.DPS_GROUND_GROUND.value] + army_entry[InfluenceMapEntry.DPS_AIR_GROUND.value]


        # army_entry = self.ai.combat.army_map[self.unit.position]
        # army_hp = army_entry[InfluenceMapEntry.HP_AIR.value] + army_entry[InfluenceMapEntry.HP_GROUND.value]

        # enemy_entry = self.ai.combat.enemy_map[target_point]
        # enemy_hp = enemy_entry[InfluenceMapEntry.HP_AIR.value] + enemy_entry[InfluenceMapEntry.HP_GROUND.value]

        # army_value = math.sqrt(max(1, army_dps * army_hp))
        # enemy_value = math.sqrt(max(1, enemy_dps * enemy_hp))

        # confidence = army_value / (army_value + enemy_value)

        enemy = self.ai.combat.enemies.get(target.tag)
        if not enemy:
            return None

        survival_delta = self.estimated_surival - enemy.estimated_surival
        if np.isnan(survival_delta):
            if enemy.estimated_surival <= self.estimated_surival:
                survival_delta = np.inf
            else:
                survival_delta = -np.inf


        if self.unit.type_id == UnitTypeId.QUEEN and not self.ai.has_creep(self.unit.position):
            self.stance = CombatStance.FLEE
        elif self.unit.is_burrowed:
            self.stance = CombatStance.FLEE
        elif 1 < self.unit.ground_range:
            if 4 <= survival_delta:
                self.stance = CombatStance.ADVANCE
            elif 2 <= survival_delta:
                self.stance = CombatStance.FIGHT
            elif 0 <= survival_delta:
                self.stance = CombatStance.RETREAT
            else:
                self.stance = CombatStance.FLEE
        else:
            if 2 <= survival_delta:
                self.stance = CombatStance.FIGHT
            else:
                self.stance = CombatStance.FLEE

        stance = self.stance

        if stance in { CombatStance.FLEE, CombatStance.RETREAT }:
            
            unit_range = self.ai.get_unit_range(self.unit, not target.is_flying, target.is_flying)

            
            if stance == CombatStance.RETREAT:
                if not self.unit.weapon_cooldown:
                    return self.unit.attack(target.position)
                elif self.unit.radius + unit_range + target.radius + self.unit.distance_to_weapon_ready < 1 + self.unit.position.distance_to(target.position):
                    return self.unit.attack(target.position)


            if self.unit.is_flying:
                retreat_map = self.ai.combat.retreat_air
            else:
                retreat_map = self.ai.combat.retreat_ground

            i, j = self.unit.position.rounded

            g = -retreat_map[:, i, j]
            g /= max(1e-6, np.linalg.norm(g))

            gb = self.ai.pathing_border[i, j, :]
            gb /= max(1e-6, np.linalg.norm(gb))

            g -= min(0, np.dot(g, gb)) * gb
            g /= max(1e-6, np.linalg.norm(g))

            retreat_point = self.unit.position + self.unit.movement_speed * g

            return self.unit.move(retreat_point)

        # elif stance == CombatStance.RETREAT:

        #     if (
        #         (self.unit.weapon_cooldown or self.unit.is_burrowed)
        #         and self.unit.position.distance_to(target.position) <= self.unit.radius + self.ai.get_unit_range(
        #         self.unit) + target.radius + self.unit.distance_to_weapon_ready
        #     ):
        #         retreat_point = self.unit.position.towards(target.position, -12)
        #         return self.unit.move(retreat_point)
        #     elif self.unit.position.distance_to(target.position) <= self.unit.radius + self.ai.get_unit_range(
        #             self.unit) + target.radius:
        #         return self.unit.attack(target.position)
        #     else:
        #         return self.unit.attack(target.position)

        elif stance == CombatStance.FIGHT:

            return self.unit.attack(target.position)

        elif stance == CombatStance.ADVANCE:

            distance = self.unit.position.distance_to(target.position) - self.unit.radius - target.radius
            if self.unit.weapon_cooldown and 1 < distance:
                return self.unit.move(target)
            elif self.unit.position.distance_to(target.position) <= self.unit.radius + self.ai.get_unit_range(
                    self.unit) + target.radius:
                return self.unit.attack(target.position)
            else:
                return self.unit.attack(target.position)

        return None