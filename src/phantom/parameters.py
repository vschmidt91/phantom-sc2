from dataclasses import dataclass, asdict, fields

from phantom.combat.action import CombatParameters, CombatPrior
from phantom.common.utils import dataclass_from_dict


@dataclass(frozen=True)
class AgentParameters:
    combat: CombatParameters

    @classmethod
    def from_dict(cls, parameters):
        return AgentParameters(
            combat=dataclass_from_dict(CombatParameters, parameters),
        )

    def to_dict(self):
        result = {}
        for field in fields(self):
            v = getattr(self, field.name)
            for field2 in fields(v):
                result[field2.name] = getattr(v, field2.name)
        return result


AgentParameterPrior = AgentParameters(CombatPrior)
