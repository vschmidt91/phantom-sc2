from __future__ import annotations

import copy
import math
from cmath import isnan
from dataclasses import dataclass
from enum import Enum, auto
from itertools import chain
from os import truncate
from random import gauss
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Set, Union

import numpy as np
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Point2, Unit, UnitCommand
from sc2.units import Units
from scipy.cluster.vq import kmeans
from scipy.ndimage.filters import gaussian_filter
from scipy.spatial.distance import cdist
from skimage.draw import disk
from skimage.transform import rescale, resize
from sklearn.cluster import DBSCAN, KMeans

from bot.behaviors.bile import BileBehavior
from bot.cost import Cost

from ..constants import CHANGELINGS, CIVILIANS, WORKERS
from ..influence_map import InfluenceMap
from ..units.unit import AIUnit
from ..utils import center
from .cy_dijkstra import cy_dijkstra  # type: ignore

# from ..units.worker import Worker
from .module import AIModule

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

Point = tuple[int, int]
HALF = Point2((0.5, 0.5))


@dataclass
class DijkstraOutput:
    prev_x: np.ndarray
    prev_y: np.ndarray
    dist: np.ndarray

    @classmethod
    def from_cy(cls, o) -> "DijkstraOutput":
        return DijkstraOutput(
            np.asarray(o.prev_x),
            np.asarray(o.prev_y),
            np.asarray(o.dist),
        )

    def get_path(self, target: Point, limit: float = math.inf):
        path: list[Point] = []
        x, y = target
        while len(path) < limit:
            path.append((x, y))
            x2 = self.prev_x[x, y]
            y2 = self.prev_y[x, y]
            if x2 < 0:
                break
            x, y = x2, y2
        return path


class CombatModule(AIModule):
    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)
        self.confidence: float = 1.0
        self.ground_dps = np.zeros((self.ai.game_info.map_size))
        self.air_dps = np.zeros((self.ai.game_info.map_size))
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
                and (
                    behavior.unit.type_id not in CIVILIANS or (hasattr(behavior, "is_drafted") and behavior.is_drafted)
                )
            )
        ]

        self.enemies = {
            unit.tag: Enemy(unit) for unit in self.ai.unit_manager.enemies.values() if unit.type_id not in CIVILIANS
        }

        self.ground_dps[:, :] = 0.0
        self.air_dps[:, :] = 0.0
        for behavior in self.enemies.values():
            enemy = behavior.unit
            if enemy.can_attack_ground:
                r = enemy.radius + enemy.ground_range + 2.0
                d = disk(enemy.position, r, shape=self.ground_dps.shape)
                self.ground_dps[d] += enemy.ground_dps
            if enemy.can_attack_air:
                r = enemy.radius + enemy.air_range + 2.0
                d = disk(enemy.position, r, shape=self.air_dps.shape)
                self.air_dps[d] += enemy.air_dps

        retreat_cost_ground = self.ai.mediator.get_map_data_object.get_pyastar_grid() + np.log1p(self.ground_dps)
        retreat_cost_air = self.ai.mediator.get_map_data_object.get_clean_air_grid() + np.log1p(self.air_dps)
        retreat_targets = [w.position for w in self.ai.workers]
        self.retreat_ground = DijkstraOutput.from_cy(
            cy_dijkstra(
                retreat_cost_ground.astype(np.float64),
                np.array(retreat_targets, dtype=np.intp),
            )
        )
        self.retreat_air = DijkstraOutput.from_cy(
            cy_dijkstra(
                retreat_cost_air.astype(np.float64),
                np.array(retreat_targets, dtype=np.intp),
            )
        )

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
            unit = behavior.unit
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

        for behavior in chain(self.army, self.enemies.values()):
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
            unit.tag: self.target_priority(unit) for unit in self.ai.unit_manager.enemies.values()
        }

        def unit_value(cost: Cost):
            return cost.minerals + cost.vespene

        army_cost = sum(unit_value(self.ai.unit_cost[behavior.unit.type_id]) for behavior in self.army)
        enemy_cost = sum(unit_value(self.ai.unit_cost[behavior.unit.type_id]) for behavior in self.enemies.values())
        self.confidence = army_cost / max(1, army_cost + enemy_cost)


class CombatBehavior(AIUnit):
    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)
        self.stance: CombatStance = CombatStance.FIGHT
        self.targets: List[Enemy] = []
        self.threats: List[Enemy] = []
        self.dps_incoming: float = 0.0
        self.estimated_survival: float = np.inf

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
            key=lambda p: p[1],
            default=(None, 0),
        )

        if not target:
            return None
        if priority <= 0:
            return None

        enemy = self.ai.combat.enemies.get(target.tag)
        if not enemy:
            return None

        if np.isinf(self.estimated_survival):
            if np.isinf(enemy.estimated_survival):
                confidence = 0.5
            else:
                confidence = 1.0
        elif np.isinf(enemy.estimated_survival):
            confidence = 0.0
        else:
            confidence = self.estimated_survival / (self.estimated_survival + enemy.estimated_survival)

        if self.unit.type_id == UnitTypeId.QUEEN and not self.ai.has_creep(self.unit.position):
            self.stance = CombatStance.FLEE
        elif self.unit.is_burrowed:
            self.stance = CombatStance.FLEE
        elif 1 < self.unit.ground_range:
            if 3 / 4 <= confidence:
                self.stance = CombatStance.ADVANCE
            elif 2 / 4 <= confidence:
                self.stance = CombatStance.FIGHT
            elif 1 / 4 <= confidence:
                self.stance = CombatStance.RETREAT
            else:
                self.stance = CombatStance.FLEE
        else:
            if 1 / 2 <= confidence:
                self.stance = CombatStance.RETREAT
            else:
                self.stance = CombatStance.FLEE

        stance = self.stance

        if stance in {CombatStance.FLEE, CombatStance.RETREAT}:
            unit_range = self.ai.get_unit_range(self.unit, not target.is_flying, target.is_flying)

            if stance == CombatStance.RETREAT:
                if not self.unit.weapon_cooldown:
                    return self.unit.attack(target.position)
                elif (
                    self.unit.radius + unit_range + target.radius + self.unit.distance_to_weapon_ready
                    < self.unit.position.distance_to(target.position)
                ):
                    return self.unit.attack(target.position)

            if self.unit.is_flying:
                retreat_map = self.ai.combat.retreat_air
            else:
                retreat_map = self.ai.combat.retreat_ground

            # i, j = self.unit.position.rounded
            #
            # g = retreat_map[i, j, :]
            # g /= max(1e-6, np.linalg.norm(g))
            #
            # if not self.unit.is_flying:
            #     gb = self.ai.pathing_border[i, j, :]
            #     gb /= max(1e-6, np.linalg.norm(gb))
            #
            #     g -= min(0, np.dot(g, gb)) * gb
            #     g /= max(1e-6, np.linalg.norm(g))
            #
            # retreat_point = self.unit.position + self.unit.movement_speed * g

            p = self.unit.position.rounded
            if retreat_map.dist[p] == np.inf:
                retreat_point = self.ai.start_location
            else:
                retreat_path = retreat_map.get_path(p, 5)
                retreat_point = Point2(retreat_path[-1]).offset(HALF)

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
            elif (
                self.unit.position.distance_to(target.position)
                <= self.unit.radius + self.ai.get_unit_range(self.unit) + target.radius
            ):
                return self.unit.attack(target.position)
            else:
                return self.unit.attack(target.position)

        return None
