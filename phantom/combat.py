import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import product

import numpy as np
import scipy.optimize
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

from phantom.common.action import Action, Attack, HoldPosition, Move, UseAbility
from phantom.common.constants import COMBATANT_STRUCTURES, HALF
from phantom.common.distribute import distribute
from phantom.common.graph import graph_components
from phantom.common.utils import (
    calculate_dps,
    can_attack,
    pairwise_distances,
    sample_bilinear,
)
from phantom.knowledge import Knowledge
from phantom.observation import Observation


@dataclass(frozen=True)
class CombatPrediction:
    outcome: EngagementResult
    outcome_for: Mapping[int, EngagementResult]
    attacking: Mapping[int, float]


class CombatState:
    def __init__(self, bot: AresBot, knowledge: Knowledge) -> None:
        self.bot = bot
        self.knowledge = knowledge
        self.contact_range_internal = 7
        self.contact_range = 14
        self.is_attacking = set[int]()

    def step(self, observation: Observation) -> "CombatAction":
        return CombatAction(self, observation)

    def _predict_trivial(self, units: Sequence[Unit], enemy_units: Sequence[Unit]) -> EngagementResult | None:
        if not any(units) and not any(enemy_units):
            return EngagementResult.TIE
        elif not any(units):
            return EngagementResult.LOSS_OVERWHELMING
        elif not any(enemy_units):
            return EngagementResult.VICTORY_OVERWHELMING
        return None

    def _predict(self, units: Units, enemy_units: Units) -> CombatPrediction:
        if trivial := self._predict_trivial(units, enemy_units):
            return CombatPrediction(trivial, {}, {})

        all_units = [*units, *enemy_units]
        positions = [u.position for u in units]
        enemy_positions = [u.position for u in enemy_units]

        distance_matrix = pairwise_distances(positions, enemy_positions)
        contact = distance_matrix < self.contact_range
        for (i, unit), (j, enemy_unit) in product(enumerate(units), enumerate(enemy_units)):
            if not can_attack(unit, enemy_unit) and not can_attack(unit, enemy_unit):
                contact[i, j] = False

        contact_own = np.zeros((len(units), len(units)))
        contact_enemy = pairwise_distances(enemy_positions) < self.contact_range_internal
        adjacency_matrix = np.block([[contact_own, contact], [contact.T, contact_enemy]])

        components = graph_components(adjacency_matrix)

        simulator_kwargs = dict(
            good_positioning=False,
            workers_do_no_damage=False,
        )
        outcome = self.bot.mediator.can_win_fight(
            own_units=units, enemy_units=enemy_units, timing_adjust=False, **simulator_kwargs
        )

        outcome_for = dict[int, EngagementResult]()
        attacking = dict[int, float]()
        for component in components:
            local_units = [all_units[i] for i in component]
            local_own = [u for u in local_units if u.is_mine]
            local_enemies = [u for u in local_units if u.is_enemy]
            local_outcome = self._predict_trivial(local_own, local_enemies) or self.bot.mediator.can_win_fight(
                own_units=local_own,
                enemy_units=local_enemies,
                timing_adjust=True,
                **simulator_kwargs,
            )
            enemy_outcome = EngagementResult(10 - local_outcome.value)
            local_attacking = sum(1 for u in local_own if u.tag in self.is_attacking) / len(units)
            for u in local_own:
                outcome_for[u.tag] = local_outcome
                attacking[u.tag] = local_attacking
            for u in local_enemies:
                outcome_for[u.tag] = enemy_outcome

        return CombatPrediction(outcome, outcome_for, attacking)


class CombatAction:
    def __init__(self, state: CombatState, observation: Observation) -> None:
        self.state = state
        self.observation = observation

        self.enemy_values = {
            u.tag: observation.calculate_unit_value_weighted(u.type_id) for u in observation.enemy_units
        }

        if state.knowledge.is_micro_map:
            retreat_targets = list()
            for dx, dy in product([-10, 0, 10], repeat=2):
                p = observation.map_center.rounded + Point2((dx, dy))
                if observation.bot.mediator.get_ground_grid[p] == 1.0:
                    retreat_targets.append(p)
            if not retreat_targets:
                retreat_targets.append(self.observation.map_center)
        else:
            retreat_targets = list()
            for b in observation.bases_taken:
                p = state.knowledge.in_mineral_line[b]
                if state.bot.mediator.get_ground_grid[p] == 1.0:
                    retreat_targets.append(p)
            if not retreat_targets:
                combatant_positions = {
                    p
                    for u in observation.combatants
                    if state.bot.mediator.get_ground_grid[p := tuple(u.position.rounded)] == 1.0
                }
                retreat_targets.extend(combatant_positions)
            if not retreat_targets:
                logger.warning("No retreat targets, falling back to start mineral line")
                p = state.knowledge.in_mineral_line[observation.start_location.rounded]
                retreat_targets.append(p)

        self.retreat_targets = np.atleast_2d(retreat_targets).astype(int)

        self.retreat_air = cy_dijkstra(
            self.observation.bot.mediator.get_air_grid.astype(np.float64), self.retreat_targets
        )
        self.retreat_ground = cy_dijkstra(
            self.observation.bot.mediator.get_ground_grid.astype(np.float64), self.retreat_targets
        )

        self.pathing_potential = np.where(self.observation.pathing < np.inf, 0.0, 1.0)
        self.targeting_cost = self._targeting_cost()
        self.optimal_targeting = self._optimal_targeting()
        self.prediction = self.state._predict(
            self.observation.combatants
            | self.observation.overseers
            | self.observation.structures(COMBATANT_STRUCTURES),
            self.observation.enemy_combatants | self.observation.enemy_structures(COMBATANT_STRUCTURES),
        )

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
        def potential_kiting(x: np.ndarray) -> float:
            if not unit.is_flying:
                pathing = sample_bilinear(self.pathing_potential, x)
                if pathing > 0:
                    return 1e10 * pathing

            def g(u: Unit):
                unit_range = unit.air_range if u.is_flying else unit.ground_range
                enemy_range = u.air_range if unit.is_flying else u.ground_range
                d = np.linalg.norm(x - u.position) - u.radius - unit.radius
                if d < enemy_range < unit_range:
                    return enemy_range - d
                # elif unit_range < d < enemy_range:
                #     return d - unit_range
                else:
                    return 0.0

            return min((g(u) for u in self.observation.enemy_combatants), default=0.0)

        def reward_fn(x: np.ndarray) -> float:
            tuple(np.round(x).astype(int))
            reward = 0.0
            if not unit.is_flying:
                pathing = sample_bilinear(self.pathing_potential, x)
                if pathing > 0:
                    return -1e10 * pathing
            # if np.less(p, 0).any() or np.greater_equal(p, self.observation.pathing.shape).any():
            #     return -1e10
            # if not unit.is_flying and not self.observation.pathing[p]:
            #     return -1e10
            e = 1e-10
            min_time_until_attack = np.inf
            mean_time_until_counter_attack = 0.0
            for enemy in self.observation.enemy_combatants:
                unit_range = unit.air_range if enemy.is_flying else unit.ground_range
                enemy_range = enemy.air_range if unit.is_flying else enemy.ground_range
                d = enemy.distance_to(x) - unit.radius - enemy.radius
                confrontation_speed = max(e, unit.movement_speed + enemy.movement_speed)
                time_until_attack = max(0, d - unit_range) / confrontation_speed
                time_until_counter_attack = max(0, d - enemy_range) / confrontation_speed
                min_time_until_attack = min(time_until_attack, min_time_until_attack)
                mean_time_until_counter_attack += time_until_counter_attack / self.observation.enemy_combatants.amount
                # time_until_attack = max(0, d - unit_range)
                # time_until_counter_attack = max(0, d - enemy_range)
                # reward += w * (time_until_counter_attack - time_until_attack)
                # reward += time_until_counter_attack / self.observation.enemy_combatants.amount
                # reward -= d / self.observation.enemy_combatants.amount
            # reward -= min_time_until_attack
            reward += mean_time_until_counter_attack
            reward -= min_time_until_attack
            return reward

        def cost_fn(u: Unit) -> float:
            hp = u.health + u.shield
            dps = calculate_dps(unit, u)
            reward = self.enemy_values[u.tag]
            risk = np.divide(hp, dps)
            cost = np.divide(risk, reward)
            random_offset = hash((unit.tag, u.tag)) / (2**sys.hash_info.width)
            cost += 1e-10 * random_offset
            return cost

        if unit.weapon_ready and (targets := self.observation.shootable_targets.get(unit)):
            target = min(targets, key=cost_fn)
            if unit.ground_range < 1:
                return Attack(target.position)
            else:
                return Attack(target)

        if not unit.weapon_ready:
            gradient = scipy.optimize.approx_fprime(unit.position, potential_kiting)
            gradient_norm = np.linalg.norm(gradient)
            if gradient_norm > 1e-5:
                return Move(unit.position - gradient / gradient_norm)

        if not (target := self.optimal_targeting.get(unit)):
            return None

        if unit.type_id in {UnitTypeId.BANELING}:
            return Move(target.position)

        # simulate battle
        distance_scale = 0.1
        a = 0.0
        alpha = 0.0
        for u in self.observation.combatants:
            d = u.distance_to(target) - u.radius - target.radius
            w = math.exp(-distance_scale * max(0, d - u.ground_range))
            a += w
            alpha += w * u.health * u.ground_dps
        alpha /= a

        b = 0.0
        beta = 0.0
        for u in self.observation.enemy_combatants:
            d = u.distance_to(unit) - u.radius - unit.radius
            w = math.exp(-distance_scale * max(0, d - u.ground_range))
            b += w
            beta += w * u.health * u.ground_dps
        beta /= b

        lancester_power = 1.5
        lancester_a = alpha * (a**lancester_power)
        lancester_b = beta * (b**lancester_power)
        if lancester_a > lancester_b:
            a_final = ((lancester_a - lancester_b) / alpha) ** (1 / lancester_power)
            outcome = a_final / a
        else:
            b_final = ((lancester_b - lancester_a) / beta) ** (1 / lancester_power)
            outcome = -b_final / b

        # outcome = self.prediction.outcome_for[unit.tag]

        retreat_grid = (
            self.state.bot.mediator.get_air_grid if unit.is_flying else self.state.bot.mediator.get_ground_grid
        )
        retreat_map = self.retreat_air if unit.is_flying else self.retreat_ground
        p = tuple(unit.position.rounded)
        retreat_path = retreat_map.get_path(p, limit=5)

        if outcome > 0:
            if unit.ground_range < 1:
                return Attack(target.position)
            else:
                return Attack(target)
        else:
            self.state.is_attacking.discard(unit.tag)
            if retreat_grid[unit.position.rounded] > 1:
                if len(retreat_path) > 2:
                    retreat_point = Point2(retreat_path[2]).offset(HALF)
                    return Move(retreat_point)
                else:
                    return self.retreat_with_ares(unit)
            else:
                return UseAbility(AbilityId.STOP)

        # outcome_local = self.prediction.outcome_for[unit.tag]
        # attacking_local = self.prediction.attacking[unit.tag]
        #
        # p = tuple(unit.position.rounded)
        # retreat_grid = (
        #     self.state.bot.mediator.get_air_grid if unit.is_flying else self.state.bot.mediator.get_ground_grid
        # )
        # retreat_map = self.retreat_air if unit.is_flying else self.retreat_ground
        # retreat_path = retreat_map.get_path(p, limit=5)
        #
        # def inf_to_one(x):
        #     return 1 if x == np.inf else x
        #
        # retreat_dps = sum(inf_to_one(retreat_grid[p]) - 1 for p in retreat_path)
        # retreat_duration = len(retreat_path) / unit.movement_speed
        # retreat_dps * retreat_duration
        #
        # bias = 0.0
        # bias += 3 * attacking_local
        #
        # if self.observation.bot.enemy_race != Race.Zerg and not self.observation.creep[unit.position.rounded]:
        #     bias += min(0, self.prediction.outcome - EngagementResult.TIE)
        #
        # if outcome_local + bias > EngagementResult.TIE:
        #     self.state.is_attacking.add(unit.tag)
        #     if unit.ground_range < 1:
        #         return UseAbility(AbilityId.ATTACK, target.position)
        #     else:
        #         return Attack(target)
        # else:
        #     self.state.is_attacking.discard(unit.tag)
        #     if retreat_grid[unit.position.rounded] > 1:
        #         if len(retreat_path) > 2:
        #             retreat_point = Point2(retreat_path[2]).offset(HALF)
        #             return Move(retreat_point)
        #         else:
        #             return self.retreat_with_ares(unit)
        #     else:
        #         return UseAbility(AbilityId.STOP)

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
            [[cost_fn(ai, bj, distances[i, j]) for j, bj in enumerate(enemies)] for i, ai in enumerate(units)]
        )
        return cost

    def _optimal_targeting(self) -> dict[Unit, Unit]:
        units = self.observation.combatants
        enemies = self.observation.enemy_combatants

        if not any(units) or not any(enemies):
            return {}

        if self.state.knowledge.is_micro_map:
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
