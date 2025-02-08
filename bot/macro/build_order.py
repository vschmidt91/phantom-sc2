from abc import ABC, abstractmethod
from dataclasses import dataclass

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId

from bot.common.action import Action, UseAbility
from bot.common.observation import Observation
from bot.macro.planner import MacroPlan


@dataclass(frozen=True)
class BuildOrderStep:
    plans: list[MacroPlan]
    actions: list[Action]


class BuildOrder(ABC):

    @abstractmethod
    def execute(self, obs: Observation) -> BuildOrderStep | None:
        raise NotImplementedError()


@dataclass(frozen=True)
class Make(BuildOrder):

    unit: UnitTypeId
    target: int

    def execute(self, obs: Observation) -> BuildOrderStep | None:
        if obs.bot.count(self.unit, include_planned=False) < self.target:
            if obs.bot.count(self.unit) < self.target:
                return BuildOrderStep([MacroPlan(self.unit)], [])
            else:
                return BuildOrderStep([], [])
        return None


@dataclass(frozen=True)
class ExtractorTrick(BuildOrder):
    unit_type = UnitTypeId.EXTRACTOR
    at_supply = 14
    min_minerals = 40

    def execute(self, obs: Observation) -> BuildOrderStep | None:
        if self.at_supply == obs.bot.supply_used and obs.bot.supply_left <= 0:
            if 0 == obs.bot.count(self.unit_type):
                if self.min_minerals < obs.bot.minerals:
                    return BuildOrderStep([MacroPlan(self.unit_type)], [])
                else:
                    return BuildOrderStep([], [])
            units = obs.structures(self.unit_type)
            return BuildOrderStep([], [UseAbility(u, AbilityId.CANCEL) for u in units])
        return None


@dataclass(frozen=True)
class BuildOrderChain(BuildOrder):
    steps: list[BuildOrder]

    def execute(self, obs: Observation) -> BuildOrderStep | None:
        for step in self.steps:
            if result := step.execute(obs):
                return result
        return None


OVERHATCH = BuildOrderChain(
    [
        Make(UnitTypeId.DRONE, 14),
        ExtractorTrick(),
        Make(UnitTypeId.OVERLORD, 2),
        Make(UnitTypeId.HATCHERY, 2),
        Make(UnitTypeId.DRONE, 16),
        Make(UnitTypeId.EXTRACTOR, 1),
        Make(UnitTypeId.SPAWNINGPOOL, 1),
    ]
)

HATCH_FIRST = BuildOrderChain(
    [
        Make(UnitTypeId.DRONE, 13),
        Make(UnitTypeId.OVERLORD, 2),
        Make(UnitTypeId.DRONE, 16),
        Make(UnitTypeId.HATCHERY, 2),
        Make(UnitTypeId.DRONE, 17),
        Make(UnitTypeId.EXTRACTOR, 1),
        Make(UnitTypeId.SPAWNINGPOOL, 1),
    ]
)
