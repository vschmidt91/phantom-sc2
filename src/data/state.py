import math
from dataclasses import dataclass
from typing import Any

from river.proba import MultivariateGaussian
from sc2.data import Result

from src.data.constants import ParameterPrior


@dataclass(frozen=True)
class DataUpdate:
    parameters: dict[str, float]
    result: Result


@dataclass(frozen=True)
class DataState:

    parameters: MultivariateGaussian

    def __add__(self, update: DataUpdate) -> "DataState":
        parameters = self.parameters
        if update.result == Result.Victory:
            parameters.update(update.parameters)
        return DataState(parameters=parameters)

    def sample_parameters(self) -> dict[str, float]:
        return self.parameters.sample()

    def to_dict(self) -> dict[str, Any]:
        return {
            "mean": self.parameters.mu,
            "covariance": self.parameters.var.to_dict(),
            "evidence": self.parameters.n_samples,
        }

    @classmethod
    def from_priors(cls, priors: dict[str, ParameterPrior]) -> "DataState":
        parameters = MultivariateGaussian()
        parameters.update({k: p.mean for k, p in priors.items()})
        delta = math.sqrt(len(priors))
        for i in range(len(priors)):
            for d in delta, -delta:
                parameters.update(
                    {k: p.mean + (d * p.sigma if i == j else 0.0) for j, (k, p) in enumerate(priors.items())}
                )
        return DataState(
            parameters=parameters,
        )
