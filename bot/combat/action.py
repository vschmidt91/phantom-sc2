import math
from dataclasses import dataclass
from functools import cached_property, cmp_to_key

import numpy as np
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.combat.predictor import CombatOutcome, CombatPrediction, CombatPredictor
from bot.combat.presence import Presence
from bot.common.action import Action, Attack, HoldPosition, Move, UseAbility
from bot.common.assignment import Assignment
from bot.common.constants import CIVILIANS, HALF
from bot.common.utils import Point, can_attack, combine_comparers, disk
from bot.cython.dijkstra_pathing import DijkstraPathing
from bot.observation import Observation


@dataclass(frozen=True)
class CombatAction:

    observation: Observation

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

    def retreat_with(self, unit: Unit, limit=7) -> Action | None:
        if unit.type_id not in {UnitTypeId.QUEEN}:
            return self.retreat_with_ares(unit, limit=limit)
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

        if unit.weapon_ready:
            if target := max(self.observation.shootable_targets.get(unit, []), key=target_key, default=None):
                return Attack(unit, target)

        if not (target := self.optimal_targeting.get(unit)):
            return None

        attack_path = self.observation.find_path(
            unit.position,
            target.position,
            unit.is_flying,
        ).rounded
        # if not attack_path:
        #     return None
        # if len(attack_path) < 3:
        #     return None
        # advance_point = attack_path[2]
        advance_point = attack_path

        if 0 == self.enemy_presence.dps[advance_point]:
            return Move(unit, advance_point)

        safe_spot = None
        for p in [attack_path]:
            under_fire = 0 < self.enemy_presence.dps[p]

            confident = self.prediction.survival_time[target] <= self.prediction.survival_time[
                unit
            ] and self.prediction.outcome in {CombatOutcome.Victory, CombatOutcome.Draw}

            if under_fire:
                if confident:
                    if safe_spot:
                        return Move(unit, safe_spot)
                    else:
                        return Attack(unit, target)
                elif safe_spot:
                    return Move(unit, safe_spot)
                else:
                    return self.retreat_with(unit)
            safe_spot = p

        return None

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
    def retreat_air(self) -> DijkstraPathing:
        return DijkstraPathing(
            self.observation.air_pathing.astype(float) + self.threat_level, self.retreat_targets_rounded
        )

    @cached_property
    def retreat_ground(self) -> DijkstraPathing:
        return DijkstraPathing(self.observation.pathing.astype(float) + self.threat_level, self.retreat_targets_rounded)

    @cached_property
    def optimal_targeting(self) -> Assignment[Unit, Unit]:

        def cost_fn(a: Unit, b: Unit) -> float:

            d = self.observation.distance_matrix[a, b]
            r = a.air_range if b.is_flying else a.ground_range
            travel_distance = max(0.0, d - a.radius - b.radius - r - a.distance_to_weapon_ready)

            travel_time = np.divide(travel_distance, a.movement_speed)
            if can_attack(a, b):
                dps = a.air_dps if b.is_flying else a.ground_dps
            else:
                dps = 1e-8
            kill_time = np.divide(b.health + b.shield, dps)
            risk = min(1e8, travel_time + 0.1 * kill_time)
            reward = max(1e-8, self.observation.calculate_unit_value_weighted(b.type_id))
            if a.order_target == b.tag:
                reward *= 1.2
            # if b.type_id in WORKERS:
            #     reward *= 7
            if b.type_id not in CIVILIANS:
                reward *= 3

            return np.divide(risk, reward)

        if self.observation.enemy_combatants:
            optimal_assigned = len(self.observation.combatants) / len(self.observation.enemy_combatants)
            medium_assigned = math.sqrt(len(self.observation.combatants))
            max_assigned = math.ceil(max(medium_assigned, optimal_assigned))
        else:
            max_assigned = 1

        assignment = Assignment.distribute(
            self.observation.combatants,
            self.observation.enemy_combatants,
            cost_fn,
            max_assigned=max_assigned,
        )

        return assignment
