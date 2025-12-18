from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit
from sc2_helper.combat_simulator import CombatSimulator as SC2CombatSimulator
from scipy.stats import expon

from phantom.common.parameter_sampler import ParameterSampler, Prior
from phantom.common.utils import (
    air_dps_of,
    air_range_of,
    ground_dps_of,
    ground_range_of,
    pairwise_distances,
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


class CombatSimulatorParameters:
    def __init__(self, sampler: ParameterSampler) -> None:
        self.time_distribution_lambda_log = sampler.add(Prior(0.0, 0.5))
        self.distance_constant_log = sampler.add(Prior(0.5, 0.1))

    @property
    def time_distribution_lambda(self) -> float:
        return np.exp(self.time_distribution_lambda_log.value)

    @property
    def distance_constant(self) -> float:
        return np.exp(self.distance_constant_log.value)


class CombatSimulator:
    def __init__(self, bot: "PhantomBot", parameters: CombatSimulatorParameters) -> None:
        self.bot = bot
        self.parameters = parameters
        self.num_steps = 24
        self.combat_sim = SC2CombatSimulator()
        self.combat_sim.enable_timing_adjustment(True)

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

        def total_cost(t: UnitTypeId) -> float:
            cost = self.bot.cost.of(t)
            total_cost = (cost.minerals + 2 * cost.vespene) * (0.5 if t == UnitTypeId.ZERGLING else 1.0)
            return total_cost

        ground_range = np.array([ground_range_of(u) for u in units])
        air_range = np.array([air_range_of(u) for u in units])
        ground_dps = np.array([ground_dps_of(u) for u in units])
        air_dps = np.array([air_dps_of(u) for u in units])
        radius = np.array([u.radius for u in units])
        attackable = np.array([self.is_attackable(u) for u in units])
        flying = np.array([u.is_flying for u in units])
        np.array([u.health + u.shield for u in units])

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
        movement_speed = np.repeat(movement_speed_vector[:, None], len(units), axis=1) + np.repeat(
            movement_speed_vector[None, :], len(units), axis=0
        )

        q = np.linspace(start=0.0, stop=1.0, num=self.num_steps, endpoint=False)
        dist = expon(scale=3.0)
        times = dist.ppf(q)
        p = dist.pdf(times)
        weights = p / p.sum()

        mixing_enemy = np.reciprocal(self.parameters.distance_constant + distance)
        mixing_own = mixing_enemy.copy()
        mixing_own[:n1, n1:] = 0.0
        mixing_own[n1:, :n1] = 0.0
        mixing_enemy[:n1, :n1] = 0.0
        mixing_enemy[n1:, n1:] = 0.0
        np.fill_diagonal(mixing_own, 0.0)
        mixing_own /= np.maximum(1e-10, mixing_own.sum(axis=1, keepdims=True))
        mixing_enemy /= np.maximum(1e-10, mixing_enemy.sum(axis=1, keepdims=True))

        health = np.array([u.health + u.shield for u in units])
        health1 = np.array([u.health + u.shield for u in setup.units1])
        health2 = np.array([u.health + u.shield for u in setup.units2])
        np.array([total_cost(u.type_id) * u.shield_health_percentage for u in units])

        lancester1 = np.full((len(units), len(times)), 0.0)
        lancester2 = np.full((len(units), len(times)), 0.0)
        lancester_dim = 0.5
        for i, ti in enumerate(times):
            range_projection = ranges + movement_speed * ti
            in_range = distance <= range_projection
            attack_weight = np.where(in_range & (dps > 0.0), 1.0, 0.0)

            attack_probability = attack_weight / np.maximum(1e-10, np.sum(attack_weight, axis=1, keepdims=True))

            fire = attack_probability * dps
            effectiveness1 = fire.sum(1)
            effectiveness2 = fire.sum(0)

            forces = attack_probability * np.repeat(health[:, None], len(units), axis=1)
            force1 = forces.sum(1)
            force2 = forces.sum(0)

            lancester1[:, i] = effectiveness1 * np.pow(force1, lancester_dim)
            lancester2[:, i] = effectiveness2 * np.pow(force2, lancester_dim)

        advantage = np.log1p(lancester1) - np.log1p(lancester2)
        outcome_vector = advantage @ weights

        win, health_result = self.combat_sim.predict_engage(
            setup.units1, setup.units2, optimistic=True, defender_player=2
        )
        outcome_global = (
            health_result / max(1e-10, health1.sum()) if win else -health_result / max(1e-10, health2.sum())
        )

        outcome_local = {u.tag: o for u, o in zip(units, outcome_vector, strict=True)}
        result = CombatResult(outcome_local=outcome_local, outcome_global=outcome_global)
        return result
