import random
from dataclasses import dataclass
from enum import Enum, auto
from functools import cache, cached_property
from typing import Callable

import numpy as np
from bot.common.assignment import Assignment
from bot.common.constants import HALF, IMPOSSIBLE_TASK_COST
from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from scipy.optimize import LinearConstraint, milp
from sklearn.metrics import pairwise_distances

from bot.combat.presence import Presence
from bot.common.action import Action, AttackMove, HoldPosition, Move, UseAbility
from bot.common.main import BotBase
from bot.common.utils import Point, can_attack, disk
from bot.cython.dijkstra_pathing import DijkstraPathing
from bot.macro.strategy import Strategy

DpsProvider = Callable[[UnitTypeId], float]


class CombatStance(Enum):
    FLEE = auto()
    RETREAT = auto()
    HOLD = auto()
    FIGHT = auto()
    ADVANCE = auto()


@dataclass(frozen=True)
class Attack(Action):
    unit: Unit
    target: Unit

    async def execute(self, bot: BotBase) -> bool:
        if self.target.is_memory:
            return self.unit.attack(self.target.position)
        else:
            return self.unit.attack(self.target)


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

    target_assignment_max_duration = 10

    def retreat_with(self, unit: Unit, limit=5) -> Action | None:
        x = round(unit.position.x)
        y = round(unit.position.y)
        if unit.is_flying:
            retreat_map = self.retreat_air
        else:
            retreat_map = self.retreat_ground
        if retreat_map.dist[x, y] == np.inf:
            return Move(unit, random.choice(list(self.retreat_targets)))
        retreat_path = retreat_map.get_path((x, y), limit)
        if len(retreat_path) < limit:
            return None
        return Move(unit, Point2(retreat_path[-1]).offset(HALF))

    def advance_with(self, unit: Unit, limit=5) -> Action | None:
        x = round(unit.position.x)
        y = round(unit.position.y)
        if unit.is_flying:
            attack_map = self.attack_air
        else:
            attack_map = self.attack_ground
        if attack_map.dist[x, y] == np.inf:
            return Move(unit, random.choice(list(self.attack_targets)))
        attack_path = attack_map.get_path((x, y), limit)
        return Move(unit, Point2(attack_path[-1]).offset(HALF))

    def fight_with(self, unit: Unit) -> Action | None:

        is_melee = unit.ground_range < 1
        # bonus_distance = unit.sight_range if is_melee else 1
        #
        # def filter_target(t: Unit) -> bool:
        #     if t.is_hallucination:
        #         return False
        #     if t.type_id in CHANGELINGS:
        #         return False
        #     if not can_attack(unit, t) and not unit.is_detector:
        #         return False
        #     if not unit.target_in_range(t, bonus_distance + unit.distance_to_weapon_ready):
        #         return False
        #     return True
        #
        # targets = self.enemy_units.filter(filter_target)
        # if not any(targets):
        #     return None

        # target = cy_closest_to(unit.position, targets)

        if not (target := self.optimal_targeting.get(unit)):
            return None

        x = round(unit.position.x)
        y = round(unit.position.y)
        confidence = self.confidence[x, y]
        if not (retreat := self.retreat_with(unit, 3)):
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
            dps = self.dps(unit.type_id)
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
        if not self.units:
            return Assignment({})
        if not self.enemy_units:
            return Assignment({})

        @cache
        def distance_metric(a, b) -> float:
            if not can_attack(a, b):
                return IMPOSSIBLE_TASK_COST
            d = a.position.distance_to(b.position) - a.radius - b.radius  # TODO: use pathing query
            r = a.air_range if b.is_flying else a.ground_range
            travel_distance = d - r - a.distance_to_weapon_ready
            if travel_distance <= 0:
                return 0.0
            if a.movement_speed <= 0:
                return IMPOSSIBLE_TASK_COST
            eta = travel_distance / a.movement_speed
            return eta

        distance_matrix = np.array([[distance_metric(a, b) for a in self.units] for b in self.enemy_units])
        assignment_matches_unit = np.array(
            [[1 if a == u else 0 for a in self.units for b in self.enemy_units] for u in self.units]
        )
        assignment_matches_target = np.array(
            [[1 if b == t else 0 for a in self.units for b in self.enemy_units] for t in self.enemy_units]
        )
        min_assigned = self.units.amount // self.enemy_units.amount
        constraints = [
            LinearConstraint(
                assignment_matches_unit,
                np.ones([self.units.amount]),
                np.ones([self.units.amount]),
            ),
            LinearConstraint(
                assignment_matches_target,
                np.full([self.enemy_units.amount], min_assigned),
                np.full([self.enemy_units.amount], min_assigned + 1),
            ),
        ]
        options = dict(
            time_limit=self.target_assignment_max_duration / 1000,
        )
        opt = milp(
            c=distance_matrix.flat,
            constraints=constraints,
            options=options,
        )
        if not opt.success:
            logger.error(f"Target assigment failed: {opt}")
            return Assignment({})
        x_opt = opt.x.reshape((self.units.amount, self.enemy_units.amount))
        target_indices = x_opt.argmax(axis=1)
        return Assignment(
            {
                u: self.enemy_units[target_indices[i]]
                for i, u in enumerate(self.units)
                if distance_matrix[target_indices[i], i] < IMPOSSIBLE_TASK_COST
            }
        )
