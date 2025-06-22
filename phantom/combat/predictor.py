from dataclasses import dataclass
from enum import Enum, auto

import numpy as np
from ares import AresBot
from ares.consts import EngagementResult
from sc2.unit import Unit
from sc2.units import Units

from phantom.common.graph import graph_components
from phantom.common.utils import calculate_dps, pairwise_distances


class CombatOutcome(Enum):
    Victory = auto()
    Defeat = auto()
    Draw = auto()


@dataclass(frozen=True)
class CombatPrediction:
    outcome: CombatOutcome
    survival_time: dict[Unit, float]
    nearby_enemy_survival_time: dict[Unit, float]


def _required_distance(u: Unit, v: Unit) -> float:
    base_range = u.radius + (u.air_range if v.is_flying else u.ground_range) + v.radius
    distance = u.distance_to(v)
    return max(0.0, distance - base_range - u.distance_to_weapon_ready)


class CombatPredictor:
    def __init__(self, bot: AresBot, units: Units, enemy_units: Units):
        self.bot = bot
        self.units = units
        self.enemy_units = enemy_units
        self.time_horizon = 2.0
        self.prediction = self._prediction_sc2helper()

    def _prediction_sc2helper(self) -> CombatPrediction:
        def weight(a: Unit, b: Unit) -> float:
            if a.alliance == b.alliance:
                return 0
            time_to_reach = np.divide(_required_distance(a, b), a.movement_speed)
            weight = max(0, (self.time_horizon - time_to_reach) / self.time_horizon)
            return weight * calculate_dps(a, b)

        units = list(self.units + self.enemy_units)

        if not any(units):
            return CombatPrediction(CombatOutcome.Draw, {}, {})

        adjacency_matrix = np.array([[weight(u, v) > 0 for v in units] for u in units])
        components = graph_components(adjacency_matrix)
        components_unique = set(tuple(c) for c in components)

        survival_time = dict[Unit, float]()
        for component in components_unique:
            component_all_units = [units[i] for i in component]
            component_units = list(filter(lambda u: u.is_mine, component_all_units))
            component_enemies = list(filter(lambda u: u.is_enemy, component_all_units))
            if not any(component_units):
                win = False
            elif not any(component_enemies):
                win = True
            else:
                outcome = self.bot.mediator.can_win_fight(
                    own_units=component_units,
                    enemy_units=component_enemies,
                    timing_adjust=True,
                    good_positioning=True,
                    workers_do_no_damage=False,
                )
                win = outcome > EngagementResult.TIE

            for u in component_units:
                survival_time[u] = 1 if win else 0
            for u in component_enemies:
                survival_time[u] = 0 if win else 1

        return CombatPrediction(CombatOutcome.Draw, survival_time, {})

    def _prediction(self) -> CombatPrediction:
        step_time = 0.1
        max_steps = 100
        max_duration = step_time * max_steps
        if not any(self.units):
            return CombatPrediction(
                outcome=CombatOutcome.Defeat,
                survival_time={u: max_duration for u in self.enemy_units},
                nearby_enemy_survival_time={},
            )
        if not any(self.enemy_units):
            return CombatPrediction(
                outcome=CombatOutcome.Victory,
                survival_time={u: max_duration for u in self.units},
                nearby_enemy_survival_time={u: 0.0 for u in self.units},
            )

        def nan_to_zero(a: np.ndarray) -> np.ndarray:
            return np.where(np.isnan(a), 0.0, a)

        dps = step_time * np.array([[calculate_dps(u, v) for v in self.enemy_units] for u in self.units])
        enemy_dps = step_time * np.array([[calculate_dps(v, u) for v in self.enemy_units] for u in self.units])

        required_distance = np.array([[_required_distance(u, v) for v in self.enemy_units] for u in self.units])
        enemy_required_distance = np.array([[_required_distance(v, u) for v in self.enemy_units] for u in self.units])

        health = np.array([u.health + u.shield for u in self.units])
        enemy_health = np.array([u.health + u.shield for u in self.enemy_units])

        health_max = np.array([u.health_max + u.shield_max for u in self.units])
        enemy_health_max = np.array([u.health_max + u.shield_max for u in self.enemy_units])

        health = np.maximum(health, 0.5 * health_max)
        enemy_health = np.maximum(enemy_health, 0.5 * enemy_health_max)

        movement_speed = np.array([u.movement_speed for u in self.units])
        enemy_movement_speed = np.array([u.movement_speed for u in self.enemy_units])

        movement_speed = np.repeat(movement_speed[..., None], len(self.enemy_units), axis=1)
        enemy_movement_speed = np.repeat(enemy_movement_speed[None, ...], len(self.units), axis=0)

        t = 0.0

        alive = np.array([True for u in self.units])
        enemy_alive = np.array([True for u in self.enemy_units])

        survival = np.array([t for u in self.units])
        enemy_survival = np.array([t for u in self.enemy_units])

        outcome = CombatOutcome.Draw
        for _i in range(max_steps):
            potential_distance_constant = 1e-3
            potential_distance = potential_distance_constant + t * movement_speed
            enemy_potential_distance = potential_distance_constant + t * enemy_movement_speed

            attack_weight = np.clip(1 - required_distance / potential_distance, 0, 1)
            enemy_attack_weight = np.clip(1 - enemy_required_distance / enemy_potential_distance, 0, 1)

            attack_probability = nan_to_zero(attack_weight / np.sum(attack_weight, axis=1, keepdims=True))
            enemy_attack_probability = nan_to_zero(
                enemy_attack_weight / np.sum(enemy_attack_weight, axis=0, keepdims=True)
            )

            health -= (enemy_attack_probability * enemy_dps) @ enemy_alive
            enemy_health -= alive @ (attack_probability * dps)

            alive = health > 0
            enemy_alive = enemy_health > 0

            if not alive.any():
                outcome = CombatOutcome.Defeat
                break
            if not enemy_alive.any():
                outcome = CombatOutcome.Victory
                break

            survival = np.where(alive, t, survival)
            enemy_survival = np.where(enemy_alive, t, enemy_survival)

            t += step_time

        distances = pairwise_distances(
            [u.position for u in self.units],
            [u.position for u in self.enemy_units],
        )
        nearby_weighting = np.reciprocal(1 + distances)

        nearby_enemy_survival = nan_to_zero((nearby_weighting @ enemy_survival) / np.sum(nearby_weighting, axis=1))
        nearby_survival = nan_to_zero((survival @ nearby_weighting) / np.sum(nearby_weighting, axis=0))

        survival_time = dict(zip(self.units, survival, strict=False)) | dict(
            zip(self.enemy_units, enemy_survival, strict=False)
        )
        nearby_survival_time = dict(zip(self.enemy_units, nearby_survival, strict=False)) | dict(
            zip(self.units, nearby_enemy_survival, strict=False)
        )

        return CombatPrediction(outcome, survival_time, nearby_survival_time)
