from dataclasses import dataclass
from typing import Any

import numpy as np
from sc2.data import Result

from bot.parameter.constants import PARAMETER_NAMES, ParameterPrior
from bot.parameter.multivariate_normal import NormalParameters


@dataclass(frozen=True)
class BotDataUpdate:
    parameters: dict[str, float]
    result: Result


@dataclass(frozen=True)
class BotData:

    parameters: NormalParameters
    names: list[str]

    def __add__(self, update: BotDataUpdate) -> "BotData":
        parameters = self.parameters
        if update.result == Result.Victory:
            values = np.array([update.parameters[k] for k in PARAMETER_NAMES])
            parameters += NormalParameters.from_values([values])
        return BotData(parameters=parameters, names=self.names)

    def sample_parameters(self) -> dict[str, float]:
        values = np.atleast_1d(self.parameters.distribution.rvs())
        return dict(zip(self.names, values))

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameters": self.parameters.to_dict(),
            "names": self.names,
        }

    @classmethod
    def from_priors(cls, priors: dict[str, ParameterPrior]) -> "BotData":
        mean = np.array([p.mean for p in priors.values()])
        variance = np.array([p.variance for p in priors.values()])
        return BotData(
            parameters=NormalParameters(
                mean=mean,
                deviation=np.diag(variance),
                evidence=1,
            ),
            names=list(priors.keys()),
        )
