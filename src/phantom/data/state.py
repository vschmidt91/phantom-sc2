import math
from dataclasses import dataclass
from typing import Any

from river.proba import MultivariateGaussian
from sc2.data import Result

from phantom.data.constants import ParameterPrior
from phantom.data.normal import NormalParameter
from phantom.parameters import AgentParameters


@dataclass(frozen=True)
class DataState:

    parameters = MultivariateGaussian()

    def update(self, parameters: dict[str, float], result: Result) -> None:
        if result == Result.Victory:
            self.parameters.update(parameters)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mean": self.parameters.mu,
            "covariance": self.parameters.var.to_dict(),
            "evidence": self.parameters.n_samples,
        }

    def initialize(self, distributions: dict[str, NormalParameter]) -> None:
        self.parameters.update({k: p.mean for k, p in distributions.items()})
        delta = math.sqrt(len(distributions))
        for i in range(len(distributions)):
            for d in delta, -delta:
                self.parameters.update(
                    {k: p.mean + (d * p.deviation if i == j else 0.0) for j, (k, p) in enumerate(distributions.items())}
                )
