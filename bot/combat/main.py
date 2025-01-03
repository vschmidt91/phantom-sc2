import math
from dataclasses import dataclass
from functools import cached_property
from typing import Callable

import numpy as np
from ares import UnitTreeQueryType
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from sklearn.metrics import pairwise_distances

from bot.combat.presence import Presence
from bot.common.action import Action, Attack, AttackMove, HoldPosition, Move, UseAbility
from bot.common.assignment import Assignment
from bot.common.constants import HALF, IMPOSSIBLE_TASK_COST
from bot.common.main import BotBase
from bot.common.utils import Point, can_attack, disk
from bot.cython.dijkstra_pathing import DijkstraPathing
from bot.macro.strategy import Strategy

DpsProvider = Callable[[UnitTypeId], float]


@dataclass(frozen=True)
class Combat:
    bot: BotBase
    strategy: Strategy
    units: Units
    enemy_units: Units
    dps: DpsProvider
    pathing: np.ndarray
    air_pathing: np.ndarray
    retreat_targets: frozenset[Point2]
    attack_targets: frozenset[Point2]

    target_assignment_max_duration = 30

    def retreat_with(self, unit: Unit, limit=7) -> Action | None:
        # return Move(
        #     unit,
        #     self.bot.mediator.find_closest_safe_spot(
        #         from_pos=unit.position,
        #         grid=self.bot.mediator.get_air_grid if unit.is_flying else self.bot.mediator.get_ground_grid,
        #         radius=limit,
        #     ),
        # )
        x = round(unit.position.x)
        y = round(unit.position.y)
        if unit.is_flying:
            retreat_map = self.retreat_air
        else:
            retreat_map = self.retreat_ground
        if retreat_map.dist[x, y] == np.inf:
            return self.retreat_with_ares(unit, limit=limit)
        retreat_path = retreat_map.get_path((x, y), limit)
        if len(retreat_path) < limit:
            return self.retreat_with_ares(unit, limit=limit)
        return Move(unit, Point2(retreat_path[2]).offset(HALF))

    def retreat_with_ares(self, unit: Unit, limit=5) -> Action | None:
        return Move(
            unit,
            self.bot.mediator.find_closest_safe_spot(
                from_pos=unit.position,
                grid=self.bot.mediator.get_air_grid if unit.is_flying else self.bot.mediator.get_ground_grid,
                radius=limit,
            ),
        )

    def advance_with(self, unit: Unit, limit=5) -> Action | None:
        x = round(unit.position.x)
        y = round(unit.position.y)
        if unit.is_flying:
            attack_map = self.attack_air
        else:
            attack_map = self.attack_ground
        if attack_map.dist[x, y] == np.inf:
            target = min(list(self.attack_targets), key=lambda p: unit.distance_to(p))
            return Move(unit, target)
        attack_path = attack_map.get_path((x, y), limit)
        return Move(unit, Point2(attack_path[-1]).offset(HALF))

    def fight_with(self, unit: Unit) -> Action | None:

        x = round(unit.position.x)
        y = round(unit.position.y)
        confidence = self.confidence[x, y]
        # confidence = +1.0

        if unit.can_attack_both:
            query_tree = UnitTreeQueryType.AllEnemy
        elif unit.can_attack_air:
            query_tree = UnitTreeQueryType.EnemyFlying
        elif unit.can_attack_ground:
            query_tree = UnitTreeQueryType.EnemyGround
        else:
            return None

        if unit.weapon_ready:
            unit_range = max(
                [
                    unit.ground_range if unit.can_attack_ground else 0.0,
                    unit.air_range if unit.can_attack_air else 0.0,
                ]
            )
            units_in_range = self.bot.mediator.get_units_in_range(
                start_points=[unit],
                distances=[2 * unit.radius + unit_range],
                query_tree=query_tree,
            )[0].filter(lambda t: can_attack(unit, t) and unit.target_in_range(t))

            def target_priority(u: Unit) -> float:
                dps = unit.air_dps if u.is_flying else unit.ground_dps
                num_hits = math.ceil(max(dps, u.health + u.shield) / dps)
                v = self.bot.calculate_unit_value(u.type_id)
                total_value = 5 * v.minerals + 12 * v.vespene
                return np.divide(total_value, num_hits)

            if target := max(units_in_range, key=target_priority, default=None):
                return Attack(unit, target)

        is_melee = unit.ground_range < 1

        if not (target := self.optimal_targeting.get(unit)):
            return None

        # confidence += self.confidence[target.position.rounded]
        # d = unit.distance_to(target)
        # confidence = self.confidence[
        #     unit.position.towards(
        #         target,
        #         max(0, 2 - unit.distance_to(target) - unit.radius - target.radius),
        #         limit=True,
        #     ).rounded
        # ]

        if not (retreat := self.retreat_with(unit)):
            return AttackMove(unit, target.position)
        elif is_melee:
            if 0 < confidence:
                return AttackMove(unit, target.position)
            else:
                return retreat
        elif 0 < confidence:
            if unit.weapon_ready:
                return AttackMove(unit, target.position)
            else:
                return self.advance_with(unit)
        elif confidence < -0.5:
            return retreat
        elif unit.weapon_ready:
            return AttackMove(unit, target.position)
        elif 0 == self.enemy_presence.dps[x, y]:
            return self.advance_with(unit)
        else:
            return retreat

    def do_unburrow(self, unit: Unit) -> Action | None:
        p = tuple[int, int](unit.position.rounded)
        confidence = self.confidence[p]
        if unit.health_percentage == 1 and 0 < confidence:
            return UseAbility(unit, AbilityId.BURROWUP)
        elif UpgradeId.TUNNELINGCLAWS not in self.bot.state.upgrades:
            return None
        elif 0 < self.enemy_presence.dps[p]:
            retreat_path = self.retreat_ground.get_path(p, 2)
            if self.retreat_ground.dist[p] == np.inf:
                retreat_point = self.bot.start_location
            else:
                retreat_point = Point2(retreat_path[-1]).offset(Point2((0.5, 0.5)))
            return Move(unit, retreat_point)
        return HoldPosition(unit)

    def do_burrow(self, unit: Unit) -> Action | None:
        if UpgradeId.BURROW not in self.bot.state.upgrades:
            return None
        elif 0.3 < unit.health_percentage:
            return None
        elif unit.is_revealed:
            return None
        elif not unit.weapon_cooldown:
            return None
        return UseAbility(unit, AbilityId.BURROWDOWN)

    @cached_property
    def presence(self) -> Presence:
        return self.get_combat_presence(self.units)

    @cached_property
    def enemy_presence(self) -> Presence:
        return self.get_combat_presence(self.enemy_units)

    def get_combat_presence(self, units: Units) -> Presence:
        dps_map = np.zeros_like(self.pathing, dtype=float)
        health_map = np.zeros_like(self.pathing, dtype=float)
        for unit in units:
            dps = max(unit.ground_dps, unit.air_dps)
            px, py = unit.position.rounded
            if 0 < dps:
                r = 2 * unit.radius
                # r += 1
                # r += max(unit.ground_range, unit.air_range)
                r += unit.sight_range
                dx, dy = disk(r)
                d = px + dx, py + dy
                health_map[d] += unit.shield + unit.health
                dps_map[d] = np.maximum(dps_map[d], dps)
        return Presence(dps_map, health_map)

    @cached_property
    def force(self) -> np.ndarray:
        return self.presence.get_force()

    @cached_property
    def enemy_force(self) -> np.ndarray:
        return self.enemy_presence.get_force()

    @cached_property
    def confidence(self) -> np.ndarray:
        return np.log1p(self.force) - np.log1p(self.enemy_force)

    @cached_property
    def threat_level(self) -> np.ndarray:
        return self.enemy_presence.dps

    @cached_property
    def retreat_targets_rounded(self) -> list[Point]:
        return [(int(p[0]), int(p[1])) for p in self.retreat_targets]

    @cached_property
    def attack_targets_rounded(self) -> list[Point]:
        return [(int(p[0]), int(p[1])) for p in self.attack_targets]

    @cached_property
    def retreat_air(self) -> DijkstraPathing:
        return DijkstraPathing(self.air_pathing + self.threat_level, self.retreat_targets_rounded)

    @cached_property
    def retreat_ground(self) -> DijkstraPathing:
        return DijkstraPathing(self.pathing + self.threat_level, self.retreat_targets_rounded)

    @cached_property
    def attack_air(self) -> DijkstraPathing:
        return DijkstraPathing(self.air_pathing + self.threat_level, self.attack_targets_rounded)

    @cached_property
    def attack_ground(self) -> DijkstraPathing:
        return DijkstraPathing(self.pathing + self.threat_level, self.attack_targets_rounded)

    @cached_property
    def unit_positions(self) -> np.ndarray:
        return np.array([np.asarray(u.position) for u in self.units])

    @cached_property
    def enemy_unit_positions(self) -> np.ndarray:
        return np.array([np.asarray(u.position) for u in self.enemy_units])

    @cached_property
    def distance_matrix(self) -> np.ndarray:
        return pairwise_distances(self.unit_positions, self.enemy_unit_positions)

    @cached_property
    def optimal_targeting(self) -> Assignment[Unit, Unit]:

        def distance_metric(a: Unit, b: Unit) -> float:
            if not can_attack(a, b):
                return IMPOSSIBLE_TASK_COST

            d = a.position.distance_to(b.position)  # TODO: use pathing query
            # return d
            # d = distance_dict[(a.tag, b.tag)] or a.position.distance_to(b.position)
            # dps = a.air_dps if b.is_flying else a.ground_dps
            r = a.air_range if b.is_flying else a.ground_range
            travel_distance = d - a.radius - b.radius - r - a.distance_to_weapon_ready

            travel_time = np.divide(max(0.0, travel_distance), a.movement_speed)
            # kill_time = np.divide(b.health + b.shield, dps)
            risk = travel_time  # + kill_time ?
            b_value = self.bot.calculate_unit_value(b.type_id)
            reward = 5 * b_value.minerals + 12 * b_value.vespene

            return np.divide(risk, reward)

        return Assignment.optimize(self.units, self.enemy_units, distance_metric)
