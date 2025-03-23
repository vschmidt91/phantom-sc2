from dataclasses import dataclass
from enum import Enum, auto
from functools import cached_property

import numpy as np
from sc2.unit import Unit
from sc2.units import Units

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


@dataclass(frozen=True)
class CombatPredictor:
    units: Units
    enemy_units: Units

    @cached_property
    def prediction(self) -> CombatPrediction:
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

        def calculate_required_distance(u: Unit, v: Unit) -> float:
            base_range = u.radius + (u.air_range if v.is_flying else u.ground_range) + v.radius
            distance = u.distance_to(v)
            return max(0.0, distance - base_range - u.distance_to_weapon_ready)

        required_distance = np.array(
            [[calculate_required_distance(u, v) for v in self.enemy_units] for u in self.units]
        )
        enemy_required_distance = np.array(
            [[calculate_required_distance(v, u) for v in self.enemy_units] for u in self.units]
        )

        health = np.array([u.health + u.shield for u in self.units])
        enemy_health = np.array([u.health + u.shield for u in self.enemy_units])

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
        for i in range(max_steps):
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

            alive = 0 < health
            enemy_alive = 0 < enemy_health

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

        survival_time = dict(zip(self.units, survival)) | dict(zip(self.enemy_units, enemy_survival))
        nearby_survival_time = dict(zip(self.enemy_units, nearby_survival)) | dict(
            zip(self.units, nearby_enemy_survival)
        )

        return CombatPrediction(outcome, survival_time, nearby_survival_time)
