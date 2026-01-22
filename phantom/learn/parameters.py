from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, auto

import cma
import numpy as np


@dataclass(frozen=True)
class Prior:
    mu: float = 0.0
    sigma: float = 1.0
    min: float = -np.inf
    max: float = np.inf


@dataclass
class Parameter:
    prior: Prior
    value: float


@dataclass
class ScalarTransform:
    coeffs: Sequence[Parameter]
    offset: Parameter

    @property
    def num_inputs(self) -> int:
        return len(self.coeffs) - 1

    def transform(self, values: Sequence[float]) -> float:
        return self.offset.value + sum(ci.value * vi for ci, vi in zip(self.coeffs, values, strict=False))


class OptimizationTarget(Enum):
    CostEfficiency = auto()
    MiningEfficiency = auto()
    SupplyEfficiency = auto()


class ParameterOptimizer:
    def __init__(self) -> None:
        self.strategy: cma.CMAEvolutionStrategy | None = None
        self.parameters = list[Parameter]()
        self.population = list[np.ndarray]()
        self.loss_values = list[float]()

    def load(self, other: "ParameterOptimizer") -> None:
        self.strategy = other.strategy
        self.population = other.population
        self.loss_values = other.loss_values

    def add(self, prior: Prior) -> Parameter:
        parameter = Parameter(prior, prior.mu)
        self.parameters.append(parameter)
        return parameter

    def add_scalar_transform(self, num_inputs: int, sigma: float = 1.0) -> ScalarTransform:
        mu = 0.0
        sigma_p = np.sqrt(sigma / num_inputs)
        priors = [Prior(mu, sigma_p) for _ in range(num_inputs)]
        coeffs = [self.add(p) for p in priors]
        offset = self.add(Prior(mu, sigma))
        return ScalarTransform(coeffs, offset)

    def _initialize_strategy(self) -> cma.CMAEvolutionStrategy:
        x0 = np.array([p.prior.mu for p in self.parameters])
        sigma0 = 1.0
        sigma0_vec = np.array([p.prior.sigma for p in self.parameters])
        bounds_min = [p.prior.min for p in self.parameters]
        bounds_max = [p.prior.max for p in self.parameters]
        options = cma.CMAOptions()
        options.set("CMA_stds", sigma0_vec)
        options.set("bounds", [bounds_min, bounds_max])
        strategy = cma.CMAEvolutionStrategy(x0, sigma0, options)
        return strategy

    def _set_values(self, values: np.ndarray) -> None:
        for parameter, value in zip(self.parameters, values, strict=False):
            parameter.value = float(value)

    def ask_best(self):
        if self.strategy is None:
            self.strategy = self._initialize_strategy()
        values = self.strategy.mean
        # values = np.array([p.prior.mu for p in self.parameters])
        self._set_values(values)

    def ask(self) -> None:
        if self.strategy is None:
            self.strategy = self._initialize_strategy()

        if not self.population:
            self.population = self.strategy.ask()
            self.loss_values.clear()

        values = self.population[len(self.loss_values)]
        self._set_values(values)

    def tell(self, fitness: float) -> None:
        if not self.strategy:
            raise Exception("tell was called before ask")
        self.loss_values.append(-fitness)
        if len(self.loss_values) == len(self.population):
            self.strategy.tell(self.population, self.loss_values)
            self.population.clear()
            self.loss_values.clear()


class ParameterManager:
    def __init__(self) -> None:
        self.optimize = {t: ParameterOptimizer() for t in OptimizationTarget}

    def ask_best(self):
        for opt in self.optimize.values():
            opt.ask_best()

    def ask(self):
        for opt in self.optimize.values():
            opt.ask()

    def tell(self, values: Mapping[OptimizationTarget, float]) -> None:
        for target, value in values.items():
            self.optimize[target].tell(value)

    def load(self, other) -> None:
        for t in OptimizationTarget:
            self.optimize[t].load(other.optimize[t])
