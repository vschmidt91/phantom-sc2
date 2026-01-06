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


class CombatSimulatorParameters:
    def __init__(self, sampler: ParameterSampler) -> None:
        self._time_distribution_lambda_log = sampler.add(Prior(1.0, 0.5))
        self._lancester_dimension = sampler.add(Prior(1.56, 0.1, min=1, max=2))

    @property
    def time_distribution_lambda(self) -> float:
        return np.exp(self._time_distribution_lambda_log.value)

    @property
    def lancester_dimension(self) -> float:
        return self._lancester_dimension.value


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
        bonus_range = np.array([1.0 if u.is_enemy else 0.0 for u in units])

        ground_selector = np.where(attackable & ~flying, 1.0, 0.0)
        air_selector = np.where(attackable & flying, 1.0, 0.0)
        dps = np.outer(ground_dps, ground_selector) + np.outer(air_dps, air_selector)
        ranges = np.outer(ground_range, ground_selector) + np.outer(air_range, air_selector)
        ranges += bonus_range[:, None]
        ranges += radius[:, None]
        ranges += radius[None, :]

        dps[:n1, :n1] = 0.0
        dps[n1:, n1:] = 0.0

        distance = pairwise_distances([u.position for u in units])
        movement_speed_vector = np.array([1.4 * u.real_speed if u.tag in setup.attacking else 0.0 for u in units])
        movement_speed = movement_speed_vector[:, None] + movement_speed_vector[None, :]

        mix_friendly = np.reciprocal(1 + distance)
        mix_friendly[:n1, n1:] = 0.0
        mix_friendly[n1:, :n1] = 0.0
        mix_friendly_sum = mix_friendly.sum(axis=1, keepdims=True)
        np.divide(mix_friendly, mix_friendly_sum, where=mix_friendly_sum != 0, out=mix_friendly)

        hp = np.array([u.health + u.shield for u in units])
        hp.sum() / np.maximum(1e-3, dps.max(1).sum())

        q = np.linspace(start=0.0, stop=1.0, num=self.num_steps, endpoint=False)
        dist = expon(scale=self.parameters.time_distribution_lambda)
        times = dist.ppf(q)

        lancester1 = np.full((len(units), self.num_steps), 0.0)
        lancester2 = np.full((len(units), self.num_steps), 0.0)
        lancester_pow = self.parameters.lancester_dimension
        for i, ti in enumerate(times):
            range_projection = ranges + movement_speed * ti
            alive = hp > 0
            valid = alive[:, None] & (distance <= range_projection) & (dps > 0)

            offense = np.zeros_like(valid, dtype=float)
            num_targets = valid.sum(axis=1, keepdims=True)
            np.divide(valid, num_targets, where=num_targets != 0, out=offense)

            strength = np.where(alive, 1.0, 0.0)
            fire2 = strength @ (dps * offense)
            forces2 = hp @ offense
            count2 = strength @ offense
            potential2 = fire2 * forces2 * np.power(np.maximum(1e-10, count2), lancester_pow - 2)

            dps.max(1) @ mix_friendly
            hp @ mix_friendly
            # potential1 = fire1 * forces1 * np.power(np.maximum(1e-10, count1), lancester_pow - 2)

            valid_sym = valid | valid.T
            mix = valid_sym / np.maximum(1, valid_sym.sum(0, keepdims=True))
            potential1 = potential2 @ mix

            lancester1[:, i] = potential1
            lancester2[:, i] = potential2

        advantage = lancester1 - lancester2
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
