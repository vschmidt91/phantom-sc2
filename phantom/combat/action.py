import math
from dataclasses import dataclass
from functools import cached_property
from itertools import chain, product

import numpy as np
from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from scipy import ndimage

from phantom.combat.predictor import CombatPrediction, CombatPredictor
from phantom.combat.presence import Presence
from phantom.common.action import Action, Attack, HoldPosition, Move, UseAbility
from phantom.common.assignment import Assignment
from phantom.common.constants import CIVILIANS, HALF, WORKERS
from phantom.common.distribute import distribute
from phantom.common.utils import Point, calculate_dps, can_attack, combine_comparers, disk, pairwise_distances
from phantom.cython.cy_dijkstra import DijkstraOutput, cy_dijkstra
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
    def retreat_targets(self) -> np.array:
        if self.observation.is_micro_map:
            return np.array([Point(self.observation.map_center.rounded)])
        else:
            retreat_targets = list[Point]()
            for b in self.observation.bases_taken:
                p = Point(self.observation.in_mineral_line(b).rounded)
                if 0 <= self.confidence[p]:
                    retreat_targets.append(p)
            if not retreat_targets:
                combatant_positions = {
                    p
                    for u in self.observation.combatants
                    if 0 <= self.confidence[p := Point(u.position.rounded)]
                }
                retreat_targets.extend(combatant_positions)
            if not retreat_targets:
                logger.warning("No retreat targets, falling back to start mineral line")
                p = Point(self.observation.in_mineral_line(self.observation.start_location).rounded)
                retreat_targets.append(p)
            return np.array(retreat_targets)

    @cached_property
    def prediction(self) -> CombatPrediction:
        return CombatPredictor(self.observation.combatants, self.observation.enemy_combatants).prediction

    def retreat_with(self, unit: Unit, limit=2) -> Action | None:
        x = round(unit.position.x)
        y = round(unit.position.y)
        if unit.is_flying:
            retreat_map = self.retreat_air
        else:
            retreat_map = self.retreat_ground
        if retreat_map.distance[x, y] == np.inf:
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
            dps = calculate_dps(unit, u)
            reward = self.observation.calculate_unit_value_weighted(u.type_id)
            return np.divide(hp, dps * reward)

        # if unit.type_id not in {UnitTypeId.ZERGLING} and unit.weapon_ready:
        if unit.weapon_ready:
            if targets := self.observation.shootable_targets.get(unit):
                target = min(targets, key=cost_fn)
                return Attack(unit, target)

        if not (target := self.optimal_targeting.get(unit)):
            return None

        p = Point(unit.position.rounded)
        q = Point(target.position.rounded)
        unit_range = unit.air_range if target.is_flying else unit.ground_range
        target_range = target.air_range if unit.is_flying else target.ground_range

        if unit.type_id in {UnitTypeId.BANELING}:
            return Move(unit, target.position)

        confidence_predictor = self.prediction.survival_time[unit] - self.prediction.nearby_enemy_survival_time[unit]
        confidence_map = self.confidence_filtered[p]
        confidence = max(confidence_predictor, confidence_map)
        # confidence = confidence_map
        test_position = unit.position.towards(target, 1.5)
        if 0 == self.enemy_presence.dps[test_position.rounded]:
            return Attack(unit, target)
        elif 0 <= confidence:
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
    def confidence_filtered(self) -> np.ndarray:
        return ndimage.gaussian_filter(self.confidence, sigma=7.0)

    @cached_property
    def threat_level(self) -> np.ndarray:
        return self.enemy_presence.dps

    @cached_property
    def retreat_air(self) -> DijkstraOutput:
        cost = self.observation.bot.mediator.get_air_grid.copy()
        targets = self.retreat_targets
        return cy_dijkstra(cost, targets)

    @cached_property
    def retreat_ground(self) -> DijkstraOutput:
        cost = self.observation.bot.mediator.get_ground_grid.copy()
        targets = self.retreat_targets
        return cy_dijkstra(cost, targets)

    @cached_property
    def targeting_cost(self) -> np.ndarray:
        units = self.observation.combatants
        enemies = self.observation.enemy_combatants
        distances = pairwise_distances(
            [u.position for u in units],
            [u.position for u in enemies],
        )

        def cost_fn(a: Unit, b: Unit, d: float) -> float:
            r = a.air_range if b.is_flying else a.ground_range
            travel_distance = max(0.0, d - a.radius - b.radius - r)
            time_to_reach = np.divide(travel_distance, a.movement_speed)
            dps = calculate_dps(a, b)
            time_to_kill = np.divide(b.health + b.shield, dps)
            return time_to_reach + time_to_kill

        cost = np.array(
            [[min(1e8, cost_fn(ai, bj, distances[i, j])) for j, bj in enumerate(enemies)] for i, ai in enumerate(units)]
        )
        return cost

    @cached_property
    def optimal_targeting(self) -> Assignment[Unit, Unit]:
        units = self.observation.combatants
        enemies = self.observation.enemy_combatants

        if not any(units) or not any(enemies):
            return Assignment({})

        if self.observation.is_micro_map:
            max_assigned = None
        elif enemies:
            optimal_assigned = len(units) / len(enemies)
            medium_assigned = math.sqrt(len(units))
            max_assigned = math.ceil(max(medium_assigned, optimal_assigned))
        else:
            max_assigned = 1

        cost = self.targeting_cost
        assignment = distribute(
            units,
            enemies,
            cost,
            max_assigned=max_assigned,
            lp=True,
        )
        assignment = Assignment({a: b for a, b in assignment.items() if can_attack(a, b)})

        return assignment
