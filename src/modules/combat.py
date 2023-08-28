from __future__ import annotations

from enum import Enum, auto
from itertools import chain
from typing import List, Optional

import numpy as np
from sc2.unit import Unit, UnitCommand
from sc2.position import Point3
from scipy.ndimage import gaussian_filter
from skimage.draw import disk

from src.cost import Cost

from ..constants import CHANGELINGS, CIVILIANS
from ..units.unit import AIUnit, Behavior

# from ..units.worker import Worker
from .module import AIModule


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
    def __init__(self, ai: "AIBase") -> None:
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
            unit
            for unit in self.ai.unit_manager.behavior_of_type(CombatBehavior)
            if unit.wants_to_fight()
        ]

        self.enemies = [
            unit
            for unit in self.ai.unit_manager.enemies.values()
            if unit.type_id not in CIVILIANS
        ]

        units = list(chain((u.unit.state for u in self.army), self.enemies))

        self.ground_dps.fill(0.0)
        self.air_dps.fill(0.0)
        seconds_per_iteration = self.ai.game_step / 22.4
        for enemy in self.enemies:
            if enemy.can_attack_ground:
                r = (
                    enemy.radius
                    + enemy.ground_range
                    + 1
                    + seconds_per_iteration * enemy.movement_speed
                )
                d = disk(enemy.position, r, shape=self.ground_dps.shape)
                self.ground_dps[d] += enemy.ground_dps
            if enemy.can_attack_air:
                r = (
                    enemy.radius
                    + enemy.air_range
                    + 1
                    + seconds_per_iteration * enemy.movement_speed
                )
                d = disk(enemy.position, r, shape=self.air_dps.shape)
                self.air_dps[d] += enemy.air_dps

        retreat_ground = self.ground_dps
        retreat_ground = gaussian_filter(retreat_ground, sigma=3)
        retreat_ground += 10 * self.ai.distance_ground
        retreat_ground = -np.stack(np.gradient(retreat_ground), axis=-1)
        self.retreat_ground = retreat_ground

        retreat_air = self.air_dps
        retreat_air = gaussian_filter(retreat_air, sigma=3)
        retreat_air += 10 * self.ai.distance_air
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
                # theoretical_range += 2.0 * (a.real_speed + b.real_speed)
                d = a.position.distance_to(b.position) - a.radius - b.radius
                distance[i, j] = d

                if d <= theoretical_range:
                    attack_weight[i, j] = 1.0
                else:
                    # attack_weight[i, j] = max(0.0, 2 - d / theoretical_range)
                    # else:
                    movement_speed = 1.4 * (a.real_speed + b.real_speed)
                    time_to_attack = (d - theoretical_range) / (1e-3 + movement_speed)
                    attack_weight[i, j] = max(0.0, 1.0 - time_to_attack / 3)

        attack_probability = attack_weight / (
            1e-3 + np.sum(attack_weight, axis=1, keepdims=True)
        )
        expected_dps = np.multiply(attack_probability, dps)

        health = np.array([unit.health + unit.shield for unit in units])
        dps_incoming = np.sum(expected_dps, axis=0)
        survival_time = health / (0.1 + dps_incoming)

        for combatant in self.ai.unit_manager.of_type(CombatBehavior):
            combatant.target = None

        # if self.confidence < 0.666:

        #     time_seed = int(self.ai.state.game_loop / 100)
        #     target = self.ai.townhalls[time_seed % self.ai.townhalls.amount]
        #     for unit in self.army:
        #         unit.target = target

        # else:

        if any(self.enemies):
            for i, combatant in enumerate(self.army):
                j = min(
                    (
                        j
                        for j in range(len(self.army), len(units))
                        if 0 < dps[i, j]
                    ),
                    key=lambda k: distance[i, k],
                    # key=lambda k: expected_dps[k, i],
                    default=None,
                )
                if j:
                    combatant.target = units[j]
                else:
                    combatant.target = None

                # if survival_time[j] <= survival_time[i]:
                if 3 + combatant.unit.state.weapon_cooldown <= survival_time[i]:
                    combatant.stance = CombatStance.FIGHT
                else:
                    combatant.stance = CombatStance.FLEE

        def unit_value(cost: Cost):
            return cost.minerals + cost.vespene

        army_cost = sum(
            unit_value(self.ai.unit_cost[behavior.unit.state.type_id])
            for behavior in self.army
        )
        enemy_cost = sum(
            unit_value(self.ai.unit_cost[enemy.type_id]) for enemy in self.enemies
        )
        self.confidence = (1 + army_cost) / (1 + army_cost + enemy_cost)


class CombatBehavior(Behavior):
    def __init__(self, unit: AIUnit):
        super().__init__(unit)
        self.stance: CombatStance = CombatStance.FIGHT
        self.target: Optional[Unit] = None

    def on_step(self) -> None:
        if self.ai.debug:
            if self.target is not None:
                color = (255, 255, 255)
                if self.unit.state == CombatStance.FIGHT:
                    color = (255, 0, 0)
                elif self.unit.state == CombatStance.FLEE:
                    color = (0, 0, 255)

                position_from = Point3(
                    (
                        *self.unit.state.position,
                        self.ai.get_terrain_z_height(self.unit.state.position) + 0.5,
                    )
                )

                position_to = Point3(
                    (
                        *self.target.position,
                        self.ai.get_terrain_z_height(self.target.position) + 0.5,
                    )
                )

                self.ai.client.debug_line_out(position_from, position_to, color=color)

    def wants_to_fight(self) -> bool:
        return True

    def fight(self) -> Optional[UnitCommand]:
        if not self.wants_to_fight():
            return None

        if not self.target:
            return None

        if self.stance in {CombatStance.FLEE, CombatStance.RETREAT}:
            unit_range = self.ai.get_unit_range(
                self.unit.state, not self.target.is_flying, self.target.is_flying
            )

            if self.stance == CombatStance.RETREAT:
                if not self.unit.state.weapon_cooldown:
                    return self.unit.state.attack(self.target.position)
                elif (
                    self.unit.state.radius
                    + unit_range
                    + self.target.radius
                    + self.unit.state.distance_to_weapon_ready
                    < self.unit.state.position.distance_to(self.target.position)
                ):
                    return self.unit.state.attack(self.target.position)

            if self.unit.state.is_flying:
                retreat_map = self.ai.combat.retreat_air
            else:
                retreat_map = self.ai.combat.retreat_ground

            i, j = self.unit.state.position.rounded

            g = retreat_map[i, j, :]
            g /= max(1e-6, float(np.linalg.norm(g)))

            # if not self.unit.state.is_flying:
            #     gb = self.ai.pathing_border[i, j, :]

            #     if 0 < np.linalg.norm(gb) and np.dot(g, gb) < 0:
            #         gb /= max(1e-6, np.linalg.norm(gb))

            #         g -= min(0, np.dot(g, gb)) * gb
            #         g /= max(1e-6, np.linalg.norm(g))

            retreat_point = (
                self.unit.state.position + self.unit.state.movement_speed * g
            )

            return self.unit.state.move(retreat_point)

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
            return self.unit.state.attack(self.target.position)

        # elif stance == CombatStance.ADVANCE:

        #     distance = self.unit.state.position.distance_to(target.position) - self.unit.state.radius - target.radius
        #     if self.unit.state.weapon_cooldown and 1 < distance:
        #         return self.unit.state.move(target)
        #     elif self.unit.state.position.distance_to(target.position) <= self.unit.state.radius + self.ai.get_unit_range(
        #             self.unit.state) + target.radius:
        #         return self.unit.state.attack(target.position)
        #     else:
        #         return self.unit.state.attack(target.position)

        return None
