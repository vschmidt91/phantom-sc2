from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import numpy as np
from sc2.unit import Unit
from scipy.special import expit
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
    attackable: bool = True

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
        self._time_distribution_lambda_log = params.optimize[OptimizationTarget.CostEfficiency].add(
            "time_distribution_lambda_log", Prior(0.0, 0.1)
        )
        self._lancester_dimension_logit = params.optimize[OptimizationTarget.CostEfficiency].add(
            "lancester_dimension_logit", Prior(0.0, 0.1)
        )
        self._enemy_range_bonus_log = params.optimize[OptimizationTarget.CostEfficiency].add(
            "enemy_range_bonus_log", Prior(0.0, 0.1)
        )

    @property
    def time_distribution_lambda(self) -> float:
        return np.exp(self._time_distribution_lambda_log.value)

    @property
    def lancester_dimension(self) -> float:
        return 1 + expit(self._lancester_dimension_logit.value)

    @property
    def enemy_range_bonus(self) -> float:
        return np.exp(self._enemy_range_bonus_log.value)


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

        ground_range = np.array([u.ground_range for u in units])
        air_range = np.array([u.air_range for u in units])
        ground_dps = np.array([u.ground_dps for u in units])
        air_dps = np.array([u.air_dps for u in units])
        radius = np.array([u.radius for u in units])
        attackable = np.array([u.attackable for u in units])
        flying = np.array([u.is_flying for u in units])
        bonus_range = np.array([self.parameters.enemy_range_bonus if u.is_enemy else 0.0 for u in units])

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
        movement_speed = movement_speed_vector[:, None]

        hp = np.array([u.hp for u in units])

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

            valid_sym = valid | valid.T
            mix = valid_sym / np.maximum(1, valid_sym.sum(0, keepdims=True))
            potential1 = potential2 @ mix

            lancester1[:, i] = potential1
            lancester2[:, i] = potential2

        outcome = lancester1 - lancester2
        lancester1_after = np.maximum(0.0, outcome)
        lancester2_after = -np.minimum(0.0, outcome)
        lancester1_casualties_log = np.log(np.maximum(1e-10, 1 - lancester1_after / np.maximum(1e-10, lancester1)))
        lancester2_casualties_log = np.log(np.maximum(1e-10, 1 - lancester2_after / np.maximum(1e-10, lancester2)))
        mu = (lancester1_casualties_log - lancester2_casualties_log) / 2

        outcome_vector = -mu.mean(1)
        outcome_global = float(np.tanh(outcome_vector[:n1].mean() - outcome_vector[n1:].mean()))

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
                attackable=self.is_attackable(u),
            )
            for u in setup.units1
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
                attackable=self.is_attackable(u),
            )
            for u in setup.units2
        ]
        return ModelCombatSetup(units1=units1, units2=units2, attacking=setup.attacking)

    def simulate_model(self, setup: ModelCombatSetup) -> CombatResult:
        return self.numpy_simulator.simulate(setup)

    def simulate(self, setup: CombatSetup) -> CombatResult:
        model_setup = self._to_model_setup(setup)
        local_result = self.numpy_simulator.simulate(model_setup)
        if self.combat_sim is None:
            return local_result

        health1 = max(1, sum(u.health + u.shield for u in setup.units1))
        health2 = max(1, sum(u.health + u.shield for u in setup.units2))
        win, health_result = self.combat_sim.predict_engage(
            setup.units1,
            setup.units2,
            optimistic=True,
            defender_player=2,
        )
        outcome_global = health_result / health1 if win else -health_result / health2

        return CombatResult(outcome_local=local_result.outcome_local, outcome_global=outcome_global)
