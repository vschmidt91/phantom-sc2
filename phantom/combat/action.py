import math
from dataclasses import dataclass
from functools import cached_property, cmp_to_key
from itertools import product

import numpy as np
from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from phantom.common.distribute import distribute
from phantom.combat.predictor import CombatPrediction, CombatPredictor
from phantom.combat.presence import Presence
from phantom.common.action import Action, Attack, HoldPosition, Move, UseAbility
from phantom.common.assignment import Assignment
from phantom.common.constants import CIVILIANS, HALF, WORKERS
from phantom.common.utils import Point, combine_comparers, disk, can_attack, pairwise_distances
from phantom.cython import cy_dijkstra, DijkstraOutput
from phantom.data.normal import NormalParameter
from phantom.observation import Observation


@dataclass(frozen=True)
class CombatParameters:
    target_stickiness: NormalParameter


CombatPrior = CombatParameters(
    NormalParameter.prior(-1.0, 0.1),
)


@dataclass(frozen=True)
class CombatAction:
    observation: Observation
    parameters: CombatParameters

    @cached_property
    def retreat_targets(self) -> frozenset[Point2]:
        if self.observation.is_micro_map:
            return frozenset([self.observation.map_center])
        else:
            retreat_targets = [self.observation.in_mineral_line(b) for b in self.observation.bases_taken]
            if not retreat_targets:
                retreat_targets.append(self.observation.start_location)
            return frozenset(retreat_targets)

    @cached_property
    def prediction(self) -> CombatPrediction:
        return CombatPredictor(self.observation.combatants, self.observation.enemy_combatants).prediction

    @cached_property
    def attack_targets(self) -> frozenset[Point2]:
        if self.observation.is_micro_map:
            return frozenset({u.position for u in self.observation.enemy_combatants} or {self.observation.map_center})
        else:
            attack_targets = [p.position for p in self.observation.enemy_structures]
            if not attack_targets:
                attack_targets.extend(self.observation.enemy_start_locations)
            return frozenset(attack_targets)

    def retreat_with(self, unit: Unit, limit=2) -> Action | None:
        # if unit.type_id not in {UnitTypeId.QUEEN}:
        #     return self.retreat_with_ares(unit, limit=limit)
        x = round(unit.position.x)
        y = round(unit.position.y)

        if unit.is_flying:
            retreat_map = self.retreat_air
        else:
            retreat_map = self.retreat_ground
        if retreat_map.distance[x, y] == np.inf:
            sx, sy = self.observation.map_size.rounded
            search_range = 1
            found = False
            for x2, y2 in product(
                range(max(0, x - search_range), min(sx - 1, x + search_range + 1)),
                range(max(0, y - search_range), min(sy - 1, y + search_range + 1)),
            ):
                if retreat_map.distance[x2, y2] < np.inf:
                    found = True
                    x, y = x2, y2
                    break
            if not found:
                logger.warning(f"infinite distance and no finite one nearby, falling back to ares retreating: {unit=}")
                return self.retreat_with_ares(unit, limit=limit)
        retreat_path = retreat_map.get_path((x, y), limit=limit)
        retreat_point = Point2(retreat_path[-1]).offset(HALF)
        # if unit.distance_to(retreat_point) < limit:
        #     logger.warning("too close to home, falling back to ares retreating")
        #     return self.retreat_with_ares(unit, limit=limit)
        return Move(unit, retreat_point)

    def retreat_with_ares(self, unit: Unit, limit=5) -> Action | None:
        return Move(
            unit,
            self.observation.find_safe_spot(
                unit.position,
                unit.is_flying,
                limit,
            ),
        )

    def fight_with(self, unit: Unit) -> Action | None:
        def cost_fn(u: Unit) -> float:
            hp = u.health + u.shield
            if hp == 0.0:
                return np.inf
            dps = unit.air_dps if u.is_flying else unit.ground_dps
            if dps == 0.0:
                return np.inf
            kill_time = hp / dps
            unit_value = self.observation.calculate_unit_value_weighted(u.type_id)
            return kill_time / (1 + unit_value)

        target_key = cmp_to_key(
            combine_comparers(
                [
                    lambda a, b: int(np.sign(np.nan_to_num(cost_fn(b) - cost_fn(a), posinf=+1, neginf=-1))),
                    lambda a, b: b.tag - a.tag,
                ]
            )
        )

        if unit.type_id not in {UnitTypeId.ZERGLING} and unit.weapon_ready:
            if target := max(self.observation.shootable_targets.get(unit, []), key=target_key, default=None):
                return Attack(unit, target)

        if not (target := self.optimal_targeting.get(unit)):
            return None

        if unit.type_id in {UnitTypeId.BANELING}:
            return Move(unit, target.position)

        confidence_local = self.prediction.survival_time[unit] - self.prediction.nearby_enemy_survival_time[unit]
        confidence_target = self.prediction.nearby_enemy_survival_time[target] - self.prediction.survival_time[target]
        if self.observation.is_micro_map:
            confidence = max(confidence_local, confidence_target)
        else:
            confidence = confidence_local
        test_position = unit.position.towards(target, 1.5)
        if 0 == self.enemy_presence.dps[test_position.rounded]:
            return Attack(unit, target)
        elif 0 < confidence:
            if unit.type_id in {UnitTypeId.ZERGLING}:
                return UseAbility(unit, AbilityId.ATTACK, target.position)
            return Attack(unit, target)
        else:
            return self.retreat_with(unit)

    def do_unburrow(self, unit: Unit) -> Action | None:
        p = tuple[int, int](unit.position.rounded)
        confidence = self.confidence[p]
        if unit.health_percentage == 1 and (0 < confidence or 0 == self.enemy_presence.dps[p]):
            return UseAbility(unit, AbilityId.BURROWUP)
        elif UpgradeId.TUNNELINGCLAWS not in self.observation.upgrades:
            return None
        elif 0 < self.enemy_presence.dps[p]:
            return self.retreat_with(unit)
        return HoldPosition(unit)

    def do_burrow(self, unit: Unit) -> Action | None:
        if UpgradeId.BURROW not in self.observation.upgrades:
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
        return self.get_combat_presence(self.observation.combatants)

    @cached_property
    def enemy_presence(self) -> Presence:
        return self.get_combat_presence(self.observation.enemy_combatants)

    def get_combat_presence(self, units: Units) -> Presence:
        dps_map = np.zeros_like(self.observation.pathing, dtype=float)
        health_map = np.zeros_like(self.observation.pathing, dtype=float)
        for unit in units:
            dps = max(unit.ground_dps, unit.air_dps)
            px, py = unit.position.rounded
            if 0 < dps:
                r = 0.0
                r += 2 * unit.radius
                r += 1
                r += max(unit.ground_range, unit.air_range)
                # r += unit.sight_range
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
    def retreat_air(self) -> DijkstraOutput:
        cost = self.observation.bot.mediator.get_air_grid.copy()
        targets = np.array(self.retreat_targets_rounded)
        # for t in self.retreat_targets_rounded:
        #     cost[t] *= 10
        return cy_dijkstra(cost, targets)

    @cached_property
    def retreat_ground(self) -> DijkstraOutput:
        cost = self.observation.bot.mediator.get_ground_grid.copy()
        targets = np.array(self.retreat_targets_rounded)
        # for t in self.retreat_targets_rounded:
        #     cost[t] *= 10
        return cy_dijkstra(cost, targets)

    @cached_property
    def optimal_targeting(self) -> Assignment[Unit, Unit]:
        units = self.observation.combatants
        enemies = self.observation.enemy_combatants

        if not any(units) or not any(enemies):
            return Assignment({})

        target_stickiness_reward = 1 + math.exp(self.parameters.target_stickiness.mean)

        def reward_of(b: Unit) -> float:
            reward = 1 + self.observation.calculate_unit_value_weighted(b.type_id)
            if b.is_structure:
                reward /= 5.0
            if b.type_id in WORKERS:
                reward *= 3.0
            if b.type_id not in CIVILIANS:
                reward *= 3.0
            return reward

        risk_a = np.full(len(units), 1.0)
        risk_b = np.full(len(enemies), 1.0)
        risk_outer = np.outer(risk_a, risk_b)

        reward_a = np.full(len(units), 1.0)
        reward_b = np.array([reward_of(e) for e in enemies])
        reward_outer = np.outer(reward_a, reward_b)

        cost_outer = np.divide(risk_outer, reward_outer)

        distances = pairwise_distances(
            [u.position for u in units],
            [u.position for u in enemies],
        )

        def cost_inner_fn(a: Unit, b: Unit, d: float) -> float:
            r = a.air_range if b.is_flying else a.ground_range
            travel_distance = max(0.0, d - a.radius - b.radius - r - a.distance_to_weapon_ready)

            time_to_reach = np.divide(travel_distance, a.movement_speed)
            time_to_kill = np.divide(b.health + b.shield, a.air_dps if b.is_flying else a.ground_dps)
            risk = time_to_reach + time_to_kill
            reward = 1.0
            if a.order_target == b.tag:
                reward *= target_stickiness_reward

            return np.divide(risk, reward)

        if self.observation.is_micro_map:
            max_assigned = None
        elif enemies:
            optimal_assigned = len(units) / len(enemies)
            medium_assigned = math.sqrt(len(units))
            max_assigned = math.ceil(max(medium_assigned, optimal_assigned))
        else:
            max_assigned = 1

        cost_inner = np.array(
            [
                [min(1e8, cost_inner_fn(ai, bj, distances[i, j])) for j, bj in enumerate(enemies)]
                for i, ai in enumerate(units)
            ]
        )
        cost = cost_outer * cost_inner

        assignment = distribute(
            units,
            enemies,
            cost,
            max_assigned=max_assigned,
            lp=True,
        )
        assignment = Assignment({a: b for a, b in assignment.items() if can_attack(a, b)})

        return assignment
