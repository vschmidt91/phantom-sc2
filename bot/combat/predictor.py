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
    def prediction(self, step_time: float = 1.0, max_steps: int = 20) -> CombatPrediction:

        def calculate_dps(u: Unit, v: Unit) -> float:
            return u.air_dps if v.is_flying else u.ground_dps

        health = np.array([u.health + u.shield for u in self.units])
        enemy_health = np.array([u.health + u.shield for u in self.enemy_units])

        t = 0.0

        survival = np.array([t for u in self.units])
        enemy_survival = np.array([t for u in self.enemy_units])
        for _ in range(max_steps):

            def calculate_attack_weight(u: Unit, v: Unit) -> float:
                base_range = u.radius + (u.air_range if v.is_flying else u.ground_range)
                distance = u.distance_to(v)

                required_distance = max(0.0, distance - base_range)
                potential_distance = 1e-3 + t * u.movement_speed

                return np.clip(1 - required_distance / potential_distance, 0, 1)

            dps = np.array([[calculate_dps(u, v) for v in self.enemy_units] for u in self.units])
            enemy_dps = np.array([[calculate_dps(v, u) for v in self.enemy_units] for u in self.units])

            alive = 0 < health
            enemy_alive = 0 < enemy_health

            attack_weight = np.array([[calculate_attack_weight(u, v) for v in self.enemy_units] for u in self.units])
            enemy_attack_weight = np.array(
                [[calculate_attack_weight(v, u) for v in self.enemy_units] for u in self.units]
            )

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

            if not any(alive) or not any(enemy_alive):
                break

        survival_time = dict(zip(self.units, survival)) | dict(zip(self.enemy_units, enemy_survival))
        return CombatPrediction(survival_time)
