from dataclasses import dataclass
from typing import Any

import numpy as np
from sc2.data import Result

from phantom.data.multivariate_normal import NormalParameters


@dataclass
class DataState:

    parameters: NormalParameters
    parameter_names: list[str]

    def update(self, parameters: np.ndarray, result: Result) -> None:
        if result == Result.Victory:
            self.parameters += NormalParameters.from_values([parameters])

    def to_json(self) -> dict[str, Any]:
        return {
            "parameters": self.parameters.to_json(),
            "parameter_names": self.parameter_names,
        }
