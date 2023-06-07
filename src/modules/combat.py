from __future__ import annotations
from cmath import isnan
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
        self.estimated_survival: float = np.inf


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
        self.army: List[CombatBehavior] = []
        self.enemies: List[Unit] = []

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
                and (
                    behavior.state.type_id not in CIVILIANS
                    or (hasattr(behavior, 'is_drafted') and behavior.is_drafted)
                )
            )
        ]

        self.enemies = [
            unit
            for unit in self.ai.unit_manager.enemies.values()
            if unit.type_id not in CIVILIANS
        ]

        units = list(chain(
            (u.state for u in self.army),
            self.enemies
        ))


        self.ground_dps[:, :] = 0.0
        self.air_dps[:, :] = 0.0
        for enemy in self.enemies:
            if enemy.can_attack_ground:
                r = enemy.radius + enemy.ground_range + 2.0
                d = disk(enemy.position, r, shape=self.ground_dps.shape)
                self.ground_dps[d] += enemy.ground_dps
            if enemy.can_attack_air:
                r = enemy.radius + enemy.air_range + 2.0
                d = disk(enemy.position, r, shape=self.air_dps.shape)
                self.air_dps[d] += enemy.air_dps

        retreat_ground = self.ground_dps
        retreat_ground = gaussian_filter(retreat_ground, sigma=1)
        retreat_ground += 100 * self.ai.distance_ground
        retreat_ground = -np.stack(np.gradient(retreat_ground), axis=-1)
        self.retreat_ground = retreat_ground

        retreat_air = self.air_dps
        retreat_air = gaussian_filter(retreat_air, sigma=1)
        retreat_air += 100 * self.ai.distance_air
        retreat_air = -np.stack(np.gradient(retreat_air), axis=-1)
        self.retreat_air = retreat_air


        dps = np.zeros((len(units), len(units)), dtype=float)
        distance = np.zeros_like(dps)
        attack_weight = np.zeros_like(dps)

        for i, a in enumerate(units):
            for j, b in enumerate(units):
                if a.owner_id == b.owner_id:
                    continue

                dps[i, j] = a.calculate_dps_vs_target(b)
                theoretical_range = a.air_range if b.is_flying else a.ground_range
                d = a.position.distance_to(b.position) - a.radius - b.radius
                distance[i, j] = d

                if d <= theoretical_range:
                    attack_weight[i, j] = 1.0
                else:
                    movement_speed = 1.4 * a.real_speed
                    time_to_attack = (d - theoretical_range) / (1e-3 + movement_speed)
                    attack_weight[i, j] = 1 / (1 + time_to_attack)

        attack_probability = attack_weight / np.sum(attack_weight, axis=1, keepdims=True)
        expected_dps = np.multiply(attack_probability, dps)

        health = np.array([unit.health + unit.shield for unit in units])
        dps_incoming = np.sum(expected_dps, axis=0)
        survival_time = health / (1e-3 + dps_incoming)


        if any(self.enemies):
            for i, unit in enumerate(self.army):

                j = min(
                    range(len(self.army), len(units)),
                    key=lambda k: survival_time[k] / attack_probability[i, k]
                )
                unit.target = units[j]

                if survival_time[j] < survival_time[i]:
                    unit.stance = CombatStance.FIGHT
                else:
                    unit.stance = CombatStance.FLEE
                
        else:
            for unit in self.army:
                unit.target = None

        def unit_value(cost: Cost):
            return cost.minerals + cost.vespene

        army_cost = sum(
            unit_value(self.ai.unit_cost[behavior.state.type_id])
            for behavior in self.army
        )
        enemy_cost = sum(
            unit_value(self.ai.unit_cost[enemy.type_id])
            for enemy in self.enemies
        )
        self.confidence = army_cost / max(1, army_cost + enemy_cost)

    async def on_step_bak(self):

        self.army = [
            behavior
            for behavior in self.ai.unit_manager.units.values()
            if (
                isinstance(behavior, CombatBehavior)
                and (
                    behavior.state.type_id not in CIVILIANS
                    or (hasattr(behavior, 'is_drafted') and behavior.is_drafted)
                )
            )
        ]

        self.enemies = {
            unit.tag: Enemy(unit)
            for unit in self.ai.unit_manager.enemies.values()
            if unit.type_id not in CIVILIANS
        }

        self.ground_dps[:, :] = 0.0
        self.air_dps[:, :] = 0.0
        for behavior in self.enemies:
            enemy = behavior.unit
            if enemy.can_attack_ground:
                r = enemy.radius + enemy.ground_range + 2.0
                d = disk(enemy.position, r, shape=self.ground_dps.shape)
                self.ground_dps[d] += enemy.ground_dps
            if enemy.can_attack_air:
                r = enemy.radius + enemy.air_range + 2.0
                d = disk(enemy.position, r, shape=self.air_dps.shape)
                self.air_dps[d] += enemy.air_dps

        retreat_ground = self.ground_dps
        retreat_ground = gaussian_filter(retreat_ground, sigma=1)
        retreat_ground += 100 * self.ai.distance_ground
        retreat_ground = -np.stack(np.gradient(retreat_ground), axis=-1)
        self.retreat_ground = retreat_ground

        retreat_air = self.air_dps
        retreat_air = gaussian_filter(retreat_air, sigma=1)
        retreat_air += 100 * self.ai.distance_air
        retreat_air = -np.stack(np.gradient(retreat_air), axis=-1)
        self.retreat_air = retreat_air

        def time_until_in_range(unit: Unit, target: Unit) -> float:
            if target.is_flying:
                r = unit.air_range
            else:
                r = unit.ground_range
            d = np.linalg.norm(unit.position - target.position)
            d = d - unit.radius - target.radius - r
            return d / max(1, unit.movement_speed)

        time_scale = 0.5
        for behavior in self.army:
            behavior.targets.clear()
            behavior.threats.clear()
            behavior.dps_incoming = 0.0
            unit = behavior.state
            for enemy_behavior in self.enemies.values():
                enemy = enemy_behavior.unit

                dps = unit.air_dps if enemy.is_flying else unit.ground_dps
                weight = math.exp(-max(0, time_scale * time_until_in_range(unit, enemy)))
                enemy_behavior.dps_incoming += dps * weight

                dps = enemy.air_dps if unit.is_flying else enemy.ground_dps
                weight = math.exp(-max(0, time_scale * time_until_in_range(enemy, unit)))
                behavior.dps_incoming += dps * weight

                # if (
                #     self.ai.can_attack(unit, enemy)
                #     and time_until_in_range(unit, enemy) < 3
                # ):
                #     dps = enemy.air_dps if unit.is_flying else enemy.ground_dps
                #     enemy_behavior.dps_incoming += 
                #     behavior.targets.append(enemy_behavior)
                #     enemy_behavior.threats.append(behavior)
                # if (
                #     self.ai.can_attack(enemy, unit)
                #     and time_until_in_range(enemy, unit) < 3
                # ):
                #     enemy_behavior.targets.append(behavior)
                #     behavior.threats.append(enemy_behavior)

        def dps(unit: Unit) -> float:
            return max(unit.air_dps, unit.ground_dps)

        for behavior in chain(self.army, self.enemies):
            # unit = behavior.unit
            # behavior.dps_incoming = sum(
            #    dps(e.unit) * math.exp(-max(0, )) / len(e.targets)
            #    for e in behavior.threats
            # )
            if 0 < behavior.dps_incoming:
                behavior.estimated_survival = (unit.health + unit.shield) / behavior.dps_incoming
            else:
                behavior.estimated_survival = np.inf

        self.target_priority_dict = {
            unit.tag: self.target_priority(unit)
            for unit in self.ai.unit_manager.enemies.values()
        }

        def unit_value(cost: Cost):
            return cost.minerals + cost.vespene

        army_cost = sum(
            unit_value(self.ai.unit_cost[behavior.state.type_id])
            for behavior in self.army
        )
        enemy_cost = sum(
            unit_value(self.ai.unit_cost[behavior.unit.type_id])
            for behavior in self.enemies.values()
        )
        self.confidence = army_cost / max(1, army_cost + enemy_cost)
            


class CombatBehavior(AIUnit):

    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)
        self.stance: CombatStance = CombatStance.FIGHT
        self.target: Optional[Unit] = None

    def fight(self) -> Optional[UnitCommand]:

        if not self.target:
            return None

        if self.stance in { CombatStance.FLEE, CombatStance.RETREAT }:
            
            unit_range = self.ai.get_unit_range(self.state, not self.target.is_flying, self.target.is_flying)

            if self.stance == CombatStance.RETREAT:
                if not self.state.weapon_cooldown:
                    return self.state.attack(self.target.position)
                elif self.state.radius + unit_range + self.target.radius + self.state.distance_to_weapon_ready < self.state.position.distance_to(self.target.position):
                    return self.state.attack(self.target.position)

            if self.state.is_flying:
                retreat_map = self.ai.combat.retreat_air
            else:
                retreat_map = self.ai.combat.retreat_ground

            i, j = self.state.position.rounded

            g = retreat_map[i, j, :]
            g /= max(1e-6, np.linalg.norm(g))

            if not self.state.is_flying:
                gb = self.ai.pathing_border[i, j, :]

                if (
                    0 < np.linalg.norm(gb)
                    and np.dot(g, gb) < 0
                ):
                    gb /= max(1e-6, np.linalg.norm(gb))

                    g -= min(0, np.dot(g, gb)) * gb
                    g /= max(1e-6, np.linalg.norm(g))

            retreat_point = self.state.position + self.state.movement_speed * g

            return self.state.move(retreat_point)

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

        elif self.stance == CombatStance.FIGHT:

            return self.state.attack(self.target.position)

        # elif stance == CombatStance.ADVANCE:

        #     distance = self.state.position.distance_to(target.position) - self.state.radius - target.radius
        #     if self.state.weapon_cooldown and 1 < distance:
        #         return self.state.move(target)
        #     elif self.state.position.distance_to(target.position) <= self.state.radius + self.ai.get_unit_range(
        #             self.state) + target.radius:
        #         return self.state.attack(target.position)
        #     else:
        #         return self.state.attack(target.position)

        return None