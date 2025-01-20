import math
from dataclasses import dataclass
from typing import Any

from river.proba import MultivariateGaussian
from sc2.data import Result

from bot.parameter.constants import ParameterPrior


@dataclass(frozen=True)
class BotDataUpdate:
    parameters: dict[str, float]
    result: Result


@dataclass(frozen=True)
class BotData:

    parameters: MultivariateGaussian

    def __add__(self, update: BotDataUpdate) -> "BotData":
        parameters = self.parameters
        if update.result == Result.Victory:
            parameters.update(update.parameters)
        return BotData(parameters=parameters)

    def sample_parameters(self) -> dict[str, float]:
        return self.parameters.sample()

    def to_dict(self) -> dict[str, Any]:
        return {
            "mean": self.parameters.mu,
            "covariance": self.parameters.var.to_dict(),
        }

    @classmethod
    def from_priors(cls, priors: dict[str, ParameterPrior]) -> "BotData":
        parameters = MultivariateGaussian()
        parameters.update({k: p.mean for k, p in priors.items()})
        delta = math.sqrt(len(priors))
        for i in range(len(priors)):
            for d in delta, -delta:
                parameters.update(
                    {k: p.mean + (d * p.sigma if i == j else 0.0) for j, (k, p) in enumerate(priors.items())}
                )
        return BotData(
            parameters=parameters,
        )
