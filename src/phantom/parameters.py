from dataclasses import dataclass, fields

from phantom.combat.action import CombatParameters, CombatPrior
from phantom.common.utils import dataclass_from_dict
from phantom.macro.strategy import StrategyParameters, StrategyPrior


@dataclass(frozen=True)
class AgentParameters:
    combat: CombatParameters
    strategy: StrategyParameters

    @classmethod
    def from_dict(cls, parameters):
        return AgentParameters(
            combat=dataclass_from_dict(CombatParameters, parameters),
            strategy=dataclass_from_dict(StrategyParameters, parameters),
        )

    def to_dict(self):
        result = {}
        for f in fields(self.combat):
            result[f.name] = getattr(self.combat, f.name)
        for f in fields(self.strategy):
            result[f.name] = getattr(self.strategy, f.name)
        return result


AgentPrior = AgentParameters(CombatPrior, StrategyPrior)
