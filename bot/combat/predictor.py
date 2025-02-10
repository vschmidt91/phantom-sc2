from dataclasses import dataclass
from functools import cached_property

import numpy as np
from sc2.unit import Unit
from sc2.units import Units


@dataclass(frozen=True)
class CombatPrediction:
    survival_time: dict[Unit, float]


@dataclass(frozen=True)
class CombatPredictor:
    units: Units
    enemy_units: Units

    @cached_property
    def prediction(self, step_time: float = 0.3, max_steps: int = 100) -> CombatPrediction:

        def calculate_dps(u: Unit, v: Unit) -> float:
            return u.air_dps if v.is_flying else u.ground_dps

        dps = np.array([[calculate_dps(u, v) for v in self.enemy_units] for u in self.units])
        enemy_dps = np.array([[calculate_dps(v, u) for v in self.enemy_units] for u in self.units])

        def calculate_required_distance(u: Unit, v: Unit) -> float:
            base_range = u.radius + (u.air_range if v.is_flying else u.ground_range) + v.radius
            distance = u.distance_to(v)
            return max(0.0, distance - base_range)

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

        for _ in range(max_steps):

            potential_distance = 1e-3 + t * movement_speed
            enemy_potential_distance = 1e-3 + t * enemy_movement_speed

            attack_weight = np.clip(1 - required_distance / potential_distance, 0, 1)
            enemy_attack_weight = np.clip(1 - enemy_required_distance / enemy_potential_distance, 0, 1)

            attack_probability = np.nan_to_num(attack_weight / np.sum(attack_weight, axis=1, keepdims=True))
            enemy_attack_probability = np.nan_to_num(
                enemy_attack_weight / np.sum(enemy_attack_weight, axis=0, keepdims=True)
            )

            dmg = alive @ (attack_probability * dps)
            enemy_dmg = (enemy_attack_probability * enemy_dps) @ enemy_alive

            health -= enemy_dmg * step_time
            enemy_health -= dmg * step_time

            alive = 0 < health
            enemy_alive = 0 < enemy_health

            survival = np.where(alive, t, survival)
            enemy_survival = np.where(enemy_alive, t, enemy_survival)

            t += step_time

        survival_time = dict(zip(self.units, survival)) | dict(zip(self.enemy_units, enemy_survival))
        return CombatPrediction(survival_time)
