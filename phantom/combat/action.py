import math
import sys

import numpy as np
from ares.consts import EngagementResult
from ares.main import AresBot
from cython_extensions.dijkstra import cy_dijkstra
from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from phantom.combat.predictor import CombatPredictor
from phantom.combat.presence import Presence
from phantom.common.action import Action, Attack, HoldPosition, Move, UseAbility
from phantom.common.constants import HALF
from phantom.common.distribute import distribute
from phantom.common.utils import (
    calculate_dps,
    can_attack,
    disk,
    pairwise_distances,
)
from phantom.knowledge import Knowledge
from phantom.observation import Observation


class CombatAction:
    def __init__(self, bot: AresBot, knowledge: Knowledge, observation: Observation) -> None:
        self.knowledge = knowledge
        self.observation = observation

        self.prediction = CombatPredictor(
            bot, observation.combatants | observation.overseers, observation.enemy_combatants
        ).prediction
        self.enemy_values = {
            u.tag: observation.calculate_unit_value_weighted(u.type_id) for u in observation.enemy_units
        }

        # self.presence = self._get_combat_presence(observation.combatants)
        # self.enemy_presence = self._get_combat_presence(observation.enemy_combatants)
        # self.force = self.presence.get_force()
        # self.enemy_force = self.enemy_presence.get_force()
        # self.confidence = np.log1p(self.force) - np.log1p(self.enemy_force)

        # sigma = 5
        # self.confidence_filtered = np.log1p(ndimage.gaussian_filter(self.force, sigma)) - np.log1p(
        #     ndimage.gaussian_filter(self.enemy_force, sigma)
        # )

        if self.knowledge.is_micro_map:
            self.retreat_targets = np.array([observation.map_center.rounded])
        else:
            retreat_targets = list()
            for b in self.observation.bases_taken:
                p = self.knowledge.in_mineral_line[b]
                if bot.mediator.get_ground_grid[p] == 1.0:
                    retreat_targets.append(p)
            if not retreat_targets:
                combatant_positions = {
                    p
                    for u in observation.combatants
                    if bot.mediator.get_ground_grid[p := tuple(u.position.rounded)] == 1.0
                }
                retreat_targets.extend(combatant_positions)
            if not retreat_targets:
                logger.warning("No retreat targets, falling back to start mineral line")
                p = self.knowledge.in_mineral_line[observation.start_location.rounded]
                retreat_targets.append(p)
            self.retreat_targets = np.array(retreat_targets)

        if self.knowledge.is_micro_map:
            self.runby_targets = np.array([tuple(u.position.rounded) for u in self.observation.enemy_combatants])
        else:
            self.runby_targets = np.array(
                [self.knowledge.in_mineral_line[p] for p in self.knowledge.enemy_start_locations]
            )

        self.retreat_air = cy_dijkstra(
            self.observation.bot.mediator.get_air_grid.astype(np.float64), self.retreat_targets
        )
        self.retreat_ground = cy_dijkstra(
            self.observation.bot.mediator.get_ground_grid.astype(np.float64), self.retreat_targets
        )

        self.targeting_cost = self._targeting_cost()
        self.optimal_targeting = self._optimal_targeting()

    def retreat_with(self, unit: Unit, limit=3) -> Action | None:
        x = round(unit.position.x)
        y = round(unit.position.y)
        retreat_map = self.retreat_air if unit.is_flying else self.retreat_ground
        if retreat_map.distance[x, y] == np.inf:
            return self.retreat_with_ares(unit)
        retreat_path = retreat_map.get_path((x, y), limit=limit)
        if len(retreat_path) < limit:
            return self.retreat_with_ares(unit)
        retreat_point = Point2(retreat_path[-1]).offset(HALF)
        # if unit.distance_to(retreat_point) < limit:
        #     logger.warning("too close to home, falling back to ares retreating")
        #     return self.retreat_with_ares(unit)
        return Move(retreat_point)

    def retreat_with_ares(self, unit: Unit, limit=7) -> Action | None:
        return Move(
            self.observation.find_safe_spot(
                unit.position,
                unit.is_flying,
                limit,
            ),
        )

    def fight_with_baneling(self, baneling: Unit) -> Action | None:
        if not (target := self.optimal_targeting.get(baneling)):
            return None
        return UseAbility(AbilityId.ATTACK, target.position)

    def fight_with(self, unit: Unit) -> Action | None:
        def cost_fn(u: Unit) -> float:
            hp = u.health + u.shield
            dps = calculate_dps(unit, u)
            reward = self.enemy_values[u.tag]
            risk = np.divide(hp, dps)
            cost = np.divide(risk, reward)
            random_offset = hash((unit.tag, u.tag)) / (2**sys.hash_info.width)
            cost += 1e-10 * random_offset
            return cost

        if unit.ground_range > 1 and unit.weapon_ready and (targets := self.observation.shootable_targets.get(unit)):
            target = min(targets, key=cost_fn)
            return Attack(target)

        if not (target := self.optimal_targeting.get(unit)):
            return None

        if unit.type_id in {UnitTypeId.BANELING}:
            return Move(target.position)

        outcome = self.prediction.outcome
        outcome_local = self.prediction.outcome_for.get(unit.tag, EngagementResult.VICTORY_DECISIVE)

        if outcome_local > min(outcome, EngagementResult.TIE):
            if unit.ground_range < 1:
                return UseAbility(AbilityId.ATTACK, target.position)
            return Attack(target)
        else:
            return self.retreat_with(unit)

    def do_unburrow(self, unit: Unit) -> Action | None:
        outcome = self.prediction.outcome_for.get(unit.tag, EngagementResult.VICTORY_DECISIVE)
        if unit.health_percentage > 0.9 and outcome >= EngagementResult.TIE:
            return UseAbility(AbilityId.BURROWUP)
        elif UpgradeId.TUNNELINGCLAWS not in self.observation.upgrades:
            return None
        elif outcome <= EngagementResult.LOSS_CLOSE:
            return self.retreat_with(unit)
        return HoldPosition()

    def do_burrow(self, unit: Unit) -> Action | None:
        if (
            UpgradeId.BURROW not in self.observation.upgrades
            or unit.health_percentage > 0.3
            or unit.is_revealed
            or not unit.weapon_cooldown
        ):
            return None
        return UseAbility(AbilityId.BURROWDOWN)

    def _targeting_cost(self) -> np.ndarray:
        units = self.observation.combatants
        enemies = self.observation.enemy_combatants
        distances = pairwise_distances(
            [u.position for u in units],
            [u.position for u in enemies],
        )

        def cost_fn(a: Unit, b: Unit, d: float) -> float:
            if a.order_target == b.tag and can_attack(a, b):
                return 0.0
            r = a.air_range if b.is_flying else a.ground_range
            travel_distance = max(0.0, d - a.radius - b.radius - r)
            time_to_reach = np.divide(travel_distance, a.movement_speed)
            dps = calculate_dps(a, b)
            time_to_kill = np.divide(b.health + b.shield, dps)
            random_offset = hash((a.tag, b.tag)) / (2**sys.hash_info.width)
            return time_to_reach + time_to_kill + 1e-10 * random_offset

        cost = np.array(
            [[min(1e8, cost_fn(ai, bj, distances[i, j])) for j, bj in enumerate(enemies)] for i, ai in enumerate(units)]
        )
        return cost

    def _optimal_targeting(self) -> dict[Unit, Unit]:
        units = self.observation.combatants
        enemies = self.observation.enemy_combatants

        if not any(units) or not any(enemies):
            return {}

        if self.knowledge.is_micro_map:
            max_assigned = None
        elif enemies:
            optimal_assigned = len(units) / len(enemies)
            medium_assigned = math.sqrt(len(units))
            max_assigned = math.ceil(max(medium_assigned, optimal_assigned))
        else:
            max_assigned = 1

        assignment = distribute(
            units,
            enemies,
            self.targeting_cost,
            max_assigned=max_assigned,
        )
        assignment = {a: b for a, b in assignment.items() if can_attack(a, b)}

        return assignment

    def _get_combat_presence(self, units: Units) -> Presence:
        dps_map = np.zeros_like(self.observation.pathing, dtype=float)
        health_map = np.zeros_like(self.observation.pathing, dtype=float)
        for unit in units:
            dps = max(unit.ground_dps, unit.air_dps)
            px, py = unit.position.rounded
            if dps > 0:
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
