from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import numpy as np
from sc2.unit import Unit
from scipy.stats import expon

from phantom.common.utils import (
    air_dps_of,
    air_range_of,
    ground_dps_of,
    ground_range_of,
    pairwise_distances,
)
from phantom.learn.parameters import OptimizationTarget, ParameterManager, Prior

if TYPE_CHECKING:
    from phantom.main import PhantomBot


class LanchesterParameters(Protocol):
    @property
    def time_distribution_lambda(self) -> float: ...

    @property
    def lancester_dimension(self) -> float: ...

    @property
    def enemy_range_bonus(self) -> float: ...


@dataclass
class CombatSetup:
    units1: Sequence[Unit]
    units2: Sequence[Unit]
    attacking: Set[int]


@dataclass(frozen=True)
class SimulationUnit:
    tag: int
    is_enemy: bool
    is_flying: bool
    health: float
    shield: float
    ground_dps: float
    air_dps: float
    ground_range: float
    air_range: float
    radius: float
    real_speed: float
    position: tuple[float, float]

    @property
    def hp(self) -> float:
        return self.health + self.shield


@dataclass
class ModelCombatSetup:
    units1: Sequence[SimulationUnit]
    units2: Sequence[SimulationUnit]
    attacking: Set[int]


@dataclass
class CombatResult:
    outcome_global: float
    outcome_local: Mapping[int, float]


class CombatSimulatorParameters:
    def __init__(self, params: ParameterManager) -> None:
        self._time_distribution_lambda = params.optimize[OptimizationTarget.CostEfficiency].add_softplus(
            "time_distribution_lambda", Prior(-0.18145307899181526, 0.1)
        )
        self._lancester_dimension = params.optimize[OptimizationTarget.CostEfficiency].add_sigmoid(
            "lancester_dimension", Prior(0.5, 0.1), low=1.0, high=2.0
        )
        self._enemy_range_bonus = params.optimize[OptimizationTarget.CostEfficiency].add_softplus(
            "enemy_range_bonus", Prior(1.435162085326694, 0.1)
        )

    @property
    def time_distribution_lambda(self) -> float:
        return self._time_distribution_lambda.value

    @property
    def lancester_dimension(self) -> float:
        return self._lancester_dimension.value

    @property
    def enemy_range_bonus(self) -> float:
        return self._enemy_range_bonus.value


class NumpyLanchesterSimulator:
    def __init__(self, parameters: LanchesterParameters, num_steps: int = 10) -> None:
        self.parameters = parameters
        self.num_steps = num_steps

    def _simulate_trivial(self, setup: ModelCombatSetup) -> CombatResult | None:
        if not any(setup.units1) and not any(setup.units2):
            return CombatResult(0.0, {})
        elif not any(setup.units1):
            return CombatResult(-1.0, {u.tag: 1.0 for u in setup.units2})
        elif not any(setup.units2):
            return CombatResult(1.0, {u.tag: 1.0 for u in setup.units1})
        return None

    def simulate(self, setup: ModelCombatSetup) -> CombatResult:
        if trivial_result := self._simulate_trivial(setup):
            return trivial_result

        units = [*setup.units1, *setup.units2]
        n1 = len(setup.units1)
        n = len(units)

        ground_range = np.array([u.ground_range for u in units], dtype=float)
        air_range = np.array([u.air_range for u in units], dtype=float)
        ground_dps = np.array([u.ground_dps for u in units], dtype=float)
        air_dps = np.array([u.air_dps for u in units], dtype=float)
        radius = np.array([u.radius for u in units], dtype=float)
        flying = np.array([u.is_flying for u in units], dtype=bool)
        bonus_range = np.array([self.parameters.enemy_range_bonus if u.is_enemy else 0.0 for u in units])

        ground_selector = np.where(~flying, 1.0, 0.0).astype(float)
        air_selector = np.where(flying, 1.0, 0.0).astype(float)
        dps = np.outer(ground_dps, ground_selector) + np.outer(air_dps, air_selector)
        ranges = np.outer(ground_range, ground_selector) + np.outer(air_range, air_selector)
        ranges += bonus_range[:, None]
        ranges += radius[:, None]
        ranges += radius[None, :]

        dps[:n1, :n1] = 0.0
        dps[n1:, n1:] = 0.0
        np.array([u.tag in setup.attacking for u in units], dtype=float)
        dps *= attacker_mask[:, None]

        distance = pairwise_distances([u.position for u in units])
        speed = 1.4 * np.array([u.real_speed for u in units], dtype=float)
        speed *= attacker_mask

        mix_enemy = np.reciprocal(1 + distance)
        mix_enemy[:n1, :n1] = 0.0
        mix_enemy[n1:, n1:] = 0.0
        mix_enemy_sum = mix_enemy.sum(axis=1, keepdims=True)
        np.divide(mix_enemy, mix_enemy_sum, where=mix_enemy_sum != 0, out=mix_enemy)

        hp0 = np.array([u.hp for u in units], dtype=float)
        hp = hp0.copy()

        speed_matrix = speed[:, None]
        tau = np.maximum(0.0, np.where(speed_matrix != 0, (distance - ranges) / speed_matrix, np.inf))
        tau[dps <= 0] = np.inf
        tau[np.arange(n), np.arange(n)] = np.inf

        q = (np.arange(self.num_steps, dtype=float) + 0.5) / self.num_steps
        tau_relevant = np.where((tau > 0.0) & (tau < np.inf), tau, np.nan)
        time_lambda = np.nanmean(np.nan_to_num(tau, posinf=np.nan))
        # time_dist = expon(scale=max(1e-6, self.parameters.time_distribution_lambda))
        if np.isnan(time_lambda):
            time_lambda = 1.0
        time_dist = expon(scale=time_lambda)
        # times = time_dist.ppf(q)

        times_set = set[float]()
        tau_unique = list(map(set, np.nan_to_num(tau_relevant, nan=np.inf)))
        tau_sample = [t for tau_slice in tau_unique for t in sorted(tau_slice)[:1]]
        times_set.update(tau_sample)
        times_set.update(time_dist.ppf(q))
        # times_set = set()
        times_set.add(0.0)
        times_set.add(np.inf)

        times = np.sort(list(times_set))
        weights = time_dist.cdf(times[1:]) - time_dist.cdf(times[:-1])

        lancester_pow = self.parameters.lancester_dimension
        # pressure_in1 = np.zeros((self.num_steps, n), dtype=float)
        # pressure_in2 = np.zeros_like(pressure_in1)
        pressure_acc = np.zeros(n, dtype=float)
        pressure_acc_nearby = np.zeros(n, dtype=float)
        outcome_acc = np.zeros(n, dtype=float)
        for wi, ti, dt in zip(weights, times, np.diff(times), strict=False):
            alive = hp > 0
            active = alive[:, None] & alive[None, :] & (tau <= ti) & (dps > 0)

            offense = np.zeros_like(dps, dtype=float)
            num_targets = active.sum(axis=1, keepdims=True)
            np.divide(active, num_targets, where=num_targets != 0, out=offense)

            strength = np.power(np.maximum(1e-6, hp / np.maximum(1e-6, hp0)), np.maximum(0.0, lancester_pow - 1.0))
            pressure_out = strength[:, None] * dps * offense
            pressure_in = pressure_out.sum(axis=0)
            hp = np.maximum(0.0, hp - dt * pressure_in)

            valid_sym = active | active.T
            mix = valid_sym / np.maximum(1, valid_sym.sum(0, keepdims=True))

            pressure_in_nearby = pressure_in @ mix

            pressure_acc += wi * pressure_in
            pressure_acc_nearby += wi * pressure_in_nearby
            outcome_acc += wi * np.log(np.maximum(1e-10, pressure_in_nearby) / np.maximum(1e-10, pressure_in))

        survival = hp / np.maximum(1e-6, hp0)
        own_survival = survival[:n1]
        enemy_survival = survival[n1:]
        own_mean = own_survival.mean()
        enemy_mean = enemy_survival.mean()
        outcome_global = own_mean - enemy_mean
        outcome_vector = np.concatenate([own_survival - enemy_mean, own_mean - enemy_survival])

        # outcome_matrix = pressure_in2 - pressure_in1
        # outcome_vector = outcome_matrix.mean(0)
        outcome_vector = pressure_acc_nearby - pressure_acc
        # outcome_vector = outcome_acc

        outcome_local = {u.tag: o for u, o in zip(units, outcome_vector, strict=True)}
        return CombatResult(outcome_local=outcome_local, outcome_global=outcome_global)


class CombatSimulator:
    def __init__(self, bot: "PhantomBot", parameters: CombatSimulatorParameters) -> None:
        self.bot = bot
        self.parameters = parameters
        self.numpy_simulator = NumpyLanchesterSimulator(parameters, num_steps=10)
        self.combat_sim = None
        try:
            from sc2_helper.combat_simulator import CombatSimulator as SC2CombatSimulator

            self.combat_sim = SC2CombatSimulator()
            self.combat_sim.enable_timing_adjustment(True)
        except ImportError:
            self.combat_sim = None

    def is_attackable(self, u: Unit) -> bool:
        if u.is_burrowed or u.is_cloaked:
            return self.bot.mediator.get_is_detected(unit=u, by_enemy=u.is_mine)
        return True

    def _to_model_setup(self, setup: CombatSetup) -> ModelCombatSetup:
        units1 = [
            SimulationUnit(
                tag=u.tag,
                is_enemy=u.is_enemy,
                is_flying=u.is_flying,
                health=u.health,
                shield=u.shield,
                ground_dps=ground_dps_of(u),
                air_dps=air_dps_of(u),
                ground_range=ground_range_of(u),
                air_range=air_range_of(u),
                radius=u.radius,
                real_speed=u.real_speed,
                position=(float(u.position.x), float(u.position.y)),
            )
            for u in setup.units1
            if self.is_attackable(u)
        ]
        units2 = [
            SimulationUnit(
                tag=u.tag,
                is_enemy=u.is_enemy,
                is_flying=u.is_flying,
                health=u.health,
                shield=u.shield,
                ground_dps=ground_dps_of(u),
                air_dps=air_dps_of(u),
                ground_range=ground_range_of(u),
                air_range=air_range_of(u),
                radius=u.radius,
                real_speed=u.real_speed,
                position=(float(u.position.x), float(u.position.y)),
            )
            for u in setup.units2
            if self.is_attackable(u)
        ]
        return ModelCombatSetup(units1=units1, units2=units2, attacking=setup.attacking)

    def simulate_model(self, setup: ModelCombatSetup) -> CombatResult:
        return self.numpy_simulator.simulate(setup)

    def simulate(self, setup: CombatSetup) -> CombatResult:
        model_setup = self._to_model_setup(setup)
        local_result = self.numpy_simulator.simulate(model_setup)
        if self.combat_sim is None:
            return local_result

        health1 = sum(u.health + u.shield for u in setup.units1)
        health2 = sum(u.health + u.shield for u in setup.units2)
        win, health_result = self.combat_sim.predict_engage(
            setup.units1,
            setup.units2,
            optimistic=True,
            defender_player=2,
        )

        # outcome_global = health_result / max(1, health1) if win else -health_result / max(1, health2)

        health_initial = health1 if win else health2
        if health_initial != 0.0:
            casualty_fraction = 1.0 - health_result / health_initial
            outcome_global = 0.5 * (-1 if win else 1) * np.log(casualty_fraction)
        else:
            outcome_global = 0.0

        return CombatResult(outcome_local=local_result.outcome_local, outcome_global=outcome_global)
