from dataclasses import asdict, dataclass
from typing import Any

from sc2.data import Result

from bot.parameter.normal import NormalParameter


@dataclass(frozen=True)
class BotDataUpdate:
    parameters: dict[str, float]
    result: Result


@dataclass(frozen=True)
class BotData:

    parameters: dict[str, NormalParameter]

    def __add__(self, update: BotDataUpdate) -> "BotData":
        parameters = dict(self.parameters)
        if update.result == Result.Victory:
            for key, value in update.parameters.items():
                parameters[key] += NormalParameter.from_values([value])
        return BotData(parameters=parameters)

    def sample_parameters(self) -> dict[str, float]:
        return {key: param.distribution.rvs() for key, param in self.parameters.items()}

    def to_dict(self) -> dict[str, dict[str, Any]]:
        return {key: asdict(param) for key, param in self.parameters.items()}
