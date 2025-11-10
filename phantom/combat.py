import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import product

import numpy as np
import scipy.optimize
from ares import WORKER_TYPES
from ares.consts import EngagementResult
from ares.main import AresBot
from cython_extensions import cy_attack_ready, cy_dijkstra, cy_range_vs_target
from loguru import logger
from sc2.data import Race
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
    structure_perimeter,
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

        self.combatants = (
            self.observation.combatants | self.observation.overseers | self.observation.structures(COMBATANT_STRUCTURES)
        )
        self.enemy_combatants = self.observation.enemy_combatants | self.observation.enemy_structures(
            COMBATANT_STRUCTURES
        )

        self.retreat_targets = np.atleast_2d(retreat_targets).astype(int)

        self.retreat_air = cy_dijkstra(
            self.observation.bot.mediator.get_air_grid.astype(np.float64), self.retreat_targets
        )
        self.retreat_ground = cy_dijkstra(
            self.observation.bot.mediator.get_ground_grid.astype(np.float64), self.retreat_targets
        )

        self.pathing_potential = np.where(self.observation.pathing < np.inf, 0.0, 1.0)
        self.optimal_targeting = self._optimal_targeting()

        runby_targets_list = list[tuple[int, int]]()
        for s in self.observation.enemy_structures:
            runby_targets_list.extend(structure_perimeter(s))

        for w in self.observation.enemy_units(WORKER_TYPES):
            runby_targets_list.append(w.position.rounded)

        if runby_targets_list:
            runby_targets_list.extend(self.observation.knowledge.enemy_start_locations)
            runby_targets = np.array(list(set(runby_targets_list)))
            self.runby_pathing = cy_dijkstra(
                self.observation.bot.mediator.get_ground_grid.astype(np.float64),
                runby_targets,
            )
        else:
            self.runby_pathing = None

        self.prediction = self.state.bot.mediator.can_win_fight(
            own_units=self.combatants,
            enemy_units=self.enemy_combatants,
            timing_adjust=False,
        )

        self.retreat_to_creep = False

        if self.observation.knowledge.enemy_race not in {Race.Zerg, Race.Random}:
            if self.prediction <= EngagementResult.TIE:
                self.retreat_to_creep = True
            elif self.prediction >= EngagementResult.VICTORY_DECISIVE:
                self.retreat_to_creep = False

    def retreat_with(self, unit: Unit, limit=3) -> Action | None:
        retreat_map = self.retreat_air if unit.is_flying else self.retreat_ground
        retreat_path = retreat_map.get_path(unit.position, limit=limit)
        if len(retreat_path) < limit:
            retreat_point = self.observation.find_safe_spot(
                unit.position,
                unit.is_flying,
                limit,
            )
        else:
            retreat_point = Point2(retreat_path[-1]).offset(HALF)
        return Move(retreat_point)

    def fight_with_baneling(self, baneling: Unit) -> Action | None:
        if not (target := self.optimal_targeting.get(baneling)):
            return None
        return UseAbility(AbilityId.ATTACK, target.position)

    def fight_with(self, unit: Unit) -> Action | None:
        p = tuple(unit.position.rounded)

        def potential_kiting(x: np.ndarray) -> float:
            if not unit.is_flying:
                pathing = sample_bilinear(self.pathing_potential, x)
                if pathing > 0.1:
                    return 1e10 * pathing

            def g(u: Unit):
                unit_range = cy_range_vs_target(unit=unit, target=u)
                safety_margin = u.movement_speed * 1.0
                enemy_range = cy_range_vs_target(unit=u, target=unit)
                d = np.linalg.norm(x - u.position) - u.radius - unit.radius
                if enemy_range < unit_range and d < safety_margin + enemy_range:
                    return safety_margin + enemy_range - d
                # elif unit_range < d < enemy_range:
                #     return d - unit_range
                return 0.0

            return sum(g(u) for u in self.enemy_combatants)

        def cost_fn(u: Unit) -> float:
            hp = u.health + u.shield
            dps = calculate_dps(unit, u)
            reward = self.enemy_values[u.tag]
            if u.is_structure:
                reward /= 10
            risk = np.divide(hp, dps)
            cost = np.divide(risk, reward)
            random_offset = hash((unit.tag, u.tag)) / (2**sys.hash_info.width)
            cost += 1e-10 * random_offset
            return cost

        if not (target := self.optimal_targeting.get(unit)):
            return None

        attack_ready = cy_attack_ready(bot=self.observation.bot, unit=unit, target=target)

        if attack_ready and (targets := self.observation.shootable_targets.get(unit)):
            target = min(targets, key=cost_fn)
            if unit.ground_range < 2:
                return Attack(target.position)
            else:
                return Attack(target)

        if not attack_ready and unit.ground_range >= 2:
            gradient = scipy.optimize.approx_fprime(unit.position, potential_kiting)
            gradient_norm = np.linalg.norm(gradient)
            if gradient_norm > 1e-5:
                return Move(unit.position - 2 * gradient / gradient_norm)

        if self.runby_pathing:
            runby_target = Point2(self.runby_pathing.get_path(unit.position, 4)[-1]).offset(HALF)
        else:
            runby_target = None

        if unit.type_id in {UnitTypeId.BANELING}:
            return Move(target.position)

        if not unit.is_flying and self.retreat_to_creep and not self.observation.creep[p]:
            return self.retreat_with(unit)

        # simulate battle
        c = 0.1
        eps = 1e-3
        a = 0.0
        alpha = 0.0
        for u in self.combatants:
            d = u.distance_to(target) - u.radius - target.radius
            d -= cy_range_vs_target(unit=u, target=target)
            dt = max(0, d) / max(eps, u.movement_speed)
            w = 1 / (1 + c * dt**2)
            a += w
            alpha += w * (u.health + u.shield) * (u.air_dps if target.is_flying else u.ground_dps)
        alpha /= a

        b = 0.0
        beta = 0.0
        for u in self.enemy_combatants:
            d = u.distance_to(unit) - u.radius - unit.radius
            d -= cy_range_vs_target(unit=u, target=unit)
            dt = max(0, d) / max(eps, u.movement_speed)
            w = 1 / (1 + c * dt**2)
            b += w
            beta += w * (u.health + u.shield) * (u.air_dps if unit.is_flying else u.ground_dps)
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

        # outcome_state = self.state.outcome_state.setdefault(unit.tag, 0.0)
        # outcome_state += .1 * (outcome - outcome_state)
        # self.state.outcome_state[unit.tag] = outcome_state

        retreat_grid = (
            self.state.bot.mediator.get_air_grid if unit.is_flying else self.state.bot.mediator.get_ground_grid
        )

        if outcome > 1 / 3:
            self.state.is_attacking.add(unit.tag)
        elif outcome < -1 / 3:
            self.state.is_attacking.discard(unit.tag)

        if unit.tag in self.state.is_attacking:
            should_runby = not self.observation.creep[p]
            if unit.distance_to(self.observation.start_location) < unit.distance_to(
                self.observation.knowledge.enemy_start_locations[0]
            ):
                should_runby = False

            if should_runby and unit.can_attack_ground and runby_target:
                return Attack(runby_target)
            elif unit.ground_range < 2:
                return Attack(target.position)
            else:
                return Attack(target)
        else:
            self.state.is_attacking.discard(unit.tag)
            if self.observation.bot.mediator.is_position_safe(
                grid=retreat_grid,
                position=unit.position,
            ):
                return UseAbility(AbilityId.STOP)
            else:
                return self.retreat_with(unit)

    def do_unburrow(self, unit: Unit) -> Action | None:
        if unit.health_percentage > 0.9:
            return UseAbility(AbilityId.BURROWUP)
        elif UpgradeId.TUNNELINGCLAWS not in self.observation.upgrades:
            return None
        elif self.state.bot.mediator.get_ground_grid[unit.position.rounded] > 1:
            return self.retreat_with(unit)
        return HoldPosition()

    def do_burrow(self, unit: Unit) -> Action | None:
        if (
            UpgradeId.BURROW not in self.observation.upgrades
            or unit.health_percentage > 0.3
            or unit.is_revealed
            or not unit.weapon_cooldown
            or self.state.bot.mediator.get_is_detected(unit=unit, by_enemy=True)
        ):
            return None
        return UseAbility(AbilityId.BURROWDOWN)

    def _targeting_cost(self, units: Sequence[Unit], enemies: Sequence[Unit]) -> np.ndarray:
        distances = pairwise_distances(
            [u.position for u in units],
            [u.position for u in enemies],
        )
        movement_speed = np.array([u.movement_speed for u in units])
        movement_speed = np.repeat(movement_speed[:, np.newaxis], len(enemies), axis=1)
        time_to_attack = np.divide(distances, movement_speed)

        ground_dps = np.array([u.ground_dps for u in units])
        air_dps = np.array([u.air_dps for u in units])

        def is_attackable(u: Unit) -> bool:
            if u.is_burrowed or u.is_cloaked:
                return self.observation.bot.mediator.get_is_detected(unit=u, by_enemy=u.is_mine)
            return True

        enemy_attackable = np.array([1.0 if is_attackable(u) else 0.0 for u in enemies])
        enemy_flying = np.array([1.0 if u.is_flying else 0.0 for u in enemies])
        enemy_ground = 1.0 - enemy_flying
        dps = np.outer(ground_dps, enemy_attackable * enemy_ground) + np.outer(air_dps, enemy_attackable * enemy_flying)

        enemy_hp = np.array([u.health + u.shield for u in enemies])
        enemy_hp = np.repeat(enemy_hp[np.newaxis, :], len(units), axis=0)

        time_to_kill = np.divide(enemy_hp, dps)

        cost = time_to_attack + time_to_kill

        # def cost_fn(a: Unit, b: Unit, d: float) -> float:
        #     if a.order_target == b.tag and can_attack(a, b):
        #         return 0.0
        #     r = cy_range_vs_target(unit=a, target=b)
        #     travel_distance = max(0.0, d - a.radius - b.radius - r)
        #     time_to_reach = np.divide(travel_distance, a.movement_speed)
        #     dps = calculate_dps(a, b)
        #     if (b.is_burrowed or b.is_cloaked) and not self.observation.bot.mediator.get_is_detected(
        #         unit=b, by_enemy=False
        #     ):
        #         dps = 0.0
        #     time_to_kill = np.divide(b.health + b.shield, dps)
        #     random_offset = hash((a.tag, b.tag)) / (2**sys.hash_info.width)
        #     return time_to_reach + time_to_kill + 1e-10 * random_offset
        #
        # cost = np.array(
        #     [[cost_fn(ai, bj, distances[i, j]) for j, bj in enumerate(enemies)] for i, ai in enumerate(units)]
        # )

        cost = np.nan_to_num(cost, nan=np.inf)
        return cost

    def _optimal_targeting(self) -> Mapping[Unit, Unit]:
        units = self.combatants
        enemies = self.enemy_combatants

        if not any(units) or not any(enemies):
            return {}

        cost = self._targeting_cost(units, enemies)

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
            cost,
            max_assigned=max_assigned,
        )

        return assignment
