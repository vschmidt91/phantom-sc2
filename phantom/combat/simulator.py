from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from sc2.unit import Unit
from sc2_helper.combat_simulator import CombatSimulator as SC2CombatSimulator
from sklearn.metrics import pairwise_distances

from phantom.common.utils import (
    air_dps_of,
    air_range_of,
    ground_dps_of,
    ground_range_of,
)

if TYPE_CHECKING:
    from phantom.main import PhantomBot


@dataclass
class CombatSetup:
    units1: Sequence[Unit]
    units2: Sequence[Unit]


@dataclass
class CombatResult:
    outcome_global: float
    outcome_local: Mapping[int, float]


class CombatSimulator(ABC):
    @abstractmethod
    def simulate(self, combat_setup: CombatSetup) -> CombatResult:
        raise NotImplementedError()


class StepwiseCombatSimulator(CombatSimulator):
    def __init__(self, bot: "PhantomBot") -> None:
        self.bot = bot
        self.num_steps = 100
        self.future_discount_lambda = 1.0
        self.vespene_weight = 2.0
        self.distance_constant = 1.0
        self.combat_sim = SC2CombatSimulator()

    def is_attackable(self, u: Unit) -> bool:
        if u.is_burrowed or u.is_cloaked:
            return self.bot.mediator.get_is_detected(unit=u, by_enemy=u.is_mine)
        return True

    def _simulate_trivial(self, setup: CombatSetup) -> CombatResult | None:
        if not any(setup.units1) and not any(setup.units2):
            return CombatResult(0.0, {})
        elif not any(setup.units1):
            return CombatResult(-1.0, {u.tag: 1.0 for u in setup.units2})
        elif not any(setup.units2):
            return CombatResult(1.0, {u.tag: 1.0 for u in setup.units1})
        return None

    def simulate(self, setup: CombatSetup) -> CombatResult:
        if trivial_result := self._simulate_trivial(setup):
            return trivial_result

        units = [*setup.units1, *setup.units2]
        n1 = len(setup.units1)

        costs = [self.bot.cost.of(u.type_id) for u in units]
        values = np.array(
            [
                (c.minerals + self.vespene_weight * c.vespene) / max(1.0, u.shield_max + u.health_max)
                for u, c in zip(units, costs, strict=False)
            ]
        )

        ground_range = np.array([ground_range_of(u) for u in units])
        air_range = np.array([air_range_of(u) for u in units])
        ground_dps = np.array([ground_dps_of(u) for u in units])
        air_dps = np.array([air_dps_of(u) for u in units])
        radius = np.array([u.radius for u in units])
        attackable = np.array([self.is_attackable(u) for u in units])
        flying = np.array([u.is_flying for u in units])

        ground_selector = np.where(attackable & ~flying, 1.0, 0.0)
        air_selector = np.where(attackable & flying, 1.0, 0.0)
        dps = np.outer(ground_dps, ground_selector) + np.outer(air_dps, air_selector)
        ranges = np.outer(ground_range, ground_selector) + np.outer(air_range, air_selector)
        ranges += np.repeat(radius[:, None], len(units), axis=1)
        ranges += np.repeat(radius[None, :], len(units), axis=0)

        dps[:n1, :n1] = 0.0
        dps[n1:, n1:] = 0.0

        distance = pairwise_distances([u.position for u in units])
        movement_speed_vector = np.array([1.4 * u.real_speed for u in units])
        movement_speed = np.repeat(movement_speed_vector[:, None], len(units), axis=1)

        health = np.array([u.health + u.shield for u in units])
        health_projection = health.copy()

        p = np.linspace(start=0.0, stop=1.0, num=self.num_steps, endpoint=False)
        times = -np.log(1.0 - p) / self.future_discount_lambda
        weights = 1 - p
        times_diff = np.diff(times)

        damage_accumulation = np.full((len(units)), 0.0)
        for t, dt, w in zip(times, times_diff, weights, strict=False):
            range_projection = ranges + movement_speed * np.sqrt(t)
            in_range = distance <= range_projection
            alive = health_projection > 0.0
            attack = (
                in_range
                & np.repeat(alive[:, None], len(units), axis=1)
                & np.repeat(alive[None, :], len(units), axis=0)
                & (dps > 0.0)
            )

            attack_weight = np.where(attack, 1.0, 0.0)
            attack_probability = attack_weight / np.maximum(1e-10, np.sum(attack_weight, axis=1, keepdims=True))

            damage_received = dt * (attack_probability * dps).sum(axis=0)
            damage_accumulation += w * damage_received
            health_projection -= damage_received

        mixing_enemy = np.reciprocal(self.distance_constant + distance)
        mixing_own = mixing_enemy.copy()

        mixing_own[:n1, n1:] = 0.0
        mixing_own[n1:, :n1] = 0.0
        mixing_enemy[:n1, :n1] = 0.0
        mixing_enemy[n1:, n1:] = 0.0

        mixing_own /= mixing_own.sum(axis=1, keepdims=True)
        mixing_enemy /= mixing_enemy.sum(axis=1, keepdims=True)

        losses_weighted = np.maximum(0.0, values * damage_accumulation)
        losses_own = mixing_own @ losses_weighted
        losses_enemy = mixing_enemy @ losses_weighted
        outcome_vector = (losses_enemy - losses_own) / np.maximum(1e-10, losses_enemy + losses_own)

        # losses_own_global = losses_weighted[:n1].sum()
        # losses_enemy_global = losses_weighted[n1:].sum()
        # outcome_global = (losses_enemy_global - losses_own_global) / max(1e-10, losses_enemy_global + losses_own_global)

        health1 = sum(u.health + u.shield for u in setup.units1)
        health2 = sum(u.health + u.shield for u in setup.units2)
        win, health_result = self.combat_sim.predict_engage(setup.units1, setup.units2)
        outcome_global = health_result / max(1e-10, health1) if win else -health_result / max(1e-10, health2)

        outcome_local = {u.tag: o for u, o in zip(units, outcome_vector, strict=True)}
        result = CombatResult(outcome_local=outcome_local, outcome_global=outcome_global)
        return result
