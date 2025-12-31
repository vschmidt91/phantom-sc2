from collections.abc import Mapping, Sequence, Set
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
    attacking: Set[int]


@dataclass
class CombatResult:
    outcome_global: float
    outcome_local: Mapping[int, float]


def simulate_future_vectorized(units: Sequence[Unit], times_lambda=1.0, n_steps=10, lanchester_n=1.56):
    N = len(units)

    # 1. Vector Setup
    teams = np.array([u.owner_id for u in units])  # (N,)
    hp = np.array([u.health for u in units])[:, None]  # (N, 1) Value/Health

    # Mechanics
    is_flying = np.array([u.is_flying for u in units])  # (N,)
    rng = np.array([u.range for u in units])[:, None]  # (N, 1)
    speed = np.array([u.speed for u in units])[:, None]  # (N, 1)
    coords = np.array([(u.x, u.y) for u in units])  # (N, 2)
    dist_matrix = np.linalg.norm(coords[:, None, :] - coords[None, :, :], axis=-1)

    # 2. Full DPS Matrix (N, N) - Handling Ground vs Air
    dps_g = np.array([u.ground_dps for u in units])[:, None]
    dps_a = np.array([u.air_dps for u in units])[:, None]

    # D[i,j] = DPS unit i deals to unit j (based on j's flight status)
    # Broadcast is_flying to columns (targets)
    D = np.where(is_flying[None, :], dps_a, dps_g)

    # 3. Stratified Time Sampling (Uniform Weights)
    step = 1.0 / n_steps
    q = np.linspace(step / 2, 1.0 - step / 2, n_steps)
    times = expon.ppf(q, scale=1.0 / times_lambda)

    # Accumulators for Offense (val I kill) and Defense (val killing me)
    acc_offense = np.zeros(N)
    acc_defense = np.zeros(N)

    # 4. Simulation Loop
    enemy_mask = teams[:, None] != teams[None, :]

    for t in times:
        # Project movement (linear closing)
        current_dist = np.maximum(0, dist_matrix - (speed + speed.T) * t)

        # Build Attack Matrix A (Row Stochastic)
        # Valid = Enemy AND In Range AND Can Damage
        valid = enemy_mask & (current_dist <= rng) & (D > 0)

        # Normalize rows (probability i attacks j)
        row_sums = valid.sum(axis=1, keepdims=True)
        A = np.divide(valid.astype(float), row_sums, out=np.zeros_like(D), where=row_sums != 0)

        # Effective Fire Matrix (Probability * DPS)
        E = A * D

        # Metric 1: Offense (What I destroy)
        # Sum_j (E_ij * HP_j) -> Row Sum
        offense_step = E @ hp

        # Metric 2: Defense (Who is destroying me)
        # Sum_i (HP_i * E_ij) -> Col Sum (done via Transpose dot)
        defense_step = hp.T @ E

        # Apply Generalized Lanchester Scaling (Concentration Bonus)
        # Count allies/enemies alive (approximation: everyone is alive in this heuristic)
        # Note: In a deeper sim, we'd mask dead units. Here we assume static composition over short future.
        counts = np.array([np.sum(teams == t_id) for t_id in teams])
        bonus_factors = np.power(counts, lanchester_n - 1.0)

        # Scale: My offense is boosted by my team size
        offense_step_scaled = offense_step.flatten() * bonus_factors
        # Scale: Incoming threat is boosted by enemy team size
        defense_step_scaled = defense_step.flatten() * bonus_factors

        acc_offense += offense_step_scaled
        acc_defense += defense_step_scaled

    # 5. Result: Log-Advantage per Unit
    # Average over time steps (uniform weights)
    avg_offense = acc_offense / n_steps
    avg_defense = acc_defense / n_steps

    return np.log1p(avg_offense) - np.log1p(avg_defense)


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
        np.array([u.tag in setup.attacking for u in units])

        ground_selector = np.where(attackable & ~flying, 1.0, 0.0)
        air_selector = np.where(attackable & flying, 1.0, 0.0)
        dps = np.outer(ground_dps, ground_selector) + np.outer(air_dps, air_selector)
        ranges = np.outer(ground_range, ground_selector) + np.outer(air_range, air_selector)
        ranges += np.repeat(radius[:, None], len(units), axis=1)
        ranges += np.repeat(radius[None, :], len(units), axis=0)

        dps[:n1, :n1] = 0.0
        dps[n1:, n1:] = 0.0

        distance = pairwise_distances([u.position for u in units])
        movement_speed_vector = np.array([1.4 * u.real_speed if u.tag in setup.attacking else 0.0 for u in units])
        movement_speed = np.repeat(movement_speed_vector[:, None], len(units), axis=1) + np.repeat(
            movement_speed_vector[None, :], len(units), axis=0
        )

        q = np.linspace(start=0.0, stop=1.0, num=self.num_steps, endpoint=False)
        dist = expon(scale=2.0)
        times = dist.ppf(q)

        hp = np.array([u.health + u.shield for u in units])
        dps.max(1)

        lancester1 = np.full((len(units), self.num_steps), 0.0)
        lancester2 = np.full((len(units), self.num_steps), 0.0)
        lancester_pow = 1.56
        for i, ti in enumerate(times):
            range_projection = ranges + movement_speed * ti
            alive = hp > 0
            valid = alive[:, None] & (distance <= range_projection) & (dps > 0)

            valid.sum(axis=1, keepdims=True)
            valid.sum(axis=0, keepdims=True)

            valid_sym = valid | valid.T
            mix = valid_sym / np.maximum(1, valid_sym.sum(0, keepdims=True))

            strength = np.where(alive, 1.0, 0.0)
            fire = strength @ (dps * valid)
            forces = hp @ valid
            count = valid.sum(0)

            potential2 = fire * forces * np.power(np.maximum(1, count), lancester_pow - 2)
            potential1 = potential2 @ mix

            lancester1[:, i] = potential1
            lancester2[:, i] = potential2

        advantage = np.log1p(lancester1) - np.log1p(lancester2)
        outcome_vector = advantage.mean(1)

        health1 = max(1, sum(u.health + u.shield for u in setup.units1))
        health2 = max(1, sum(u.health + u.shield for u in setup.units2))
        win, health_result = self.combat_sim.predict_engage(
            setup.units1, setup.units2, optimistic=True, defender_player=2
        )
        outcome_global = health_result / health1 if win else -health_result / health2

        outcome_local = {u.tag: o for u, o in zip(units, outcome_vector, strict=True)}
        result = CombatResult(outcome_local=outcome_local, outcome_global=outcome_global)
        return result
