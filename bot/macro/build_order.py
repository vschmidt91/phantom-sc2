from abc import ABC, abstractmethod
from dataclasses import dataclass

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId

from bot.common.action import Action, UseAbility
from bot.common.observation import Observation
from bot.macro.planner import MacroPlan


@dataclass(frozen=True)
class BuildOrderStepResult:
    plans: list[MacroPlan]
    actions: list[Action]


class BuildOrder(ABC):

    @abstractmethod
    def execute(self, obs: Observation) -> BuildOrderStepResult | None:
        raise NotImplementedError()


@dataclass(frozen=True)
class BuildUnit(BuildOrder):

    unit: UnitTypeId
    target: int

    def execute(self, obs: Observation) -> BuildOrderStepResult | None:
        # if step.only_at_supply is not None and step.only_at_supply != self.supply_used:
        #     pass
        # elif step.min_minerals and self.minerals < step.min_minerals:
        #     pass
        if obs.bot.count(self.unit, include_planned=False) >= self.target:
            return None
        elif obs.bot.count(self.unit) < self.target:
            return BuildOrderStepResult([MacroPlan(self.unit)], [])
        else:
            return BuildOrderStepResult([], [])

    only_at_supply: int | None = None
    min_minerals: int | None = None


@dataclass(frozen=True)
class ExtractorTrick(BuildOrder):
    unit_type = UnitTypeId.EXTRACTOR
    at_supply = 14
    min_minerals = 40

    def execute(self, obs: Observation) -> BuildOrderStepResult | None:
        if self.at_supply == obs.bot.supply_used and obs.bot.supply_left <= 0:
            if 0 == obs.bot.count(self.unit_type):
                if self.min_minerals < obs.bot.minerals:
                    return BuildOrderStepResult([MacroPlan(self.unit_type)], [])
                else:
                    return BuildOrderStepResult([], [])
            units = obs.structures(self.unit_type)
            return BuildOrderStepResult([], [UseAbility(u, AbilityId.CANCEL) for u in units])
        return None


@dataclass(frozen=True)
class BuildOrderChain(BuildOrder):
    steps: list[BuildOrder]

    def execute(self, obs: Observation) -> BuildOrderStepResult | None:
        for step in self.steps:
            if result := step.execute(obs):
                return result
        return None


OVERHATCH = BuildOrderChain(
    [
        BuildUnit(UnitTypeId.DRONE, 14),
        ExtractorTrick(),
        BuildUnit(UnitTypeId.OVERLORD, 2),
        BuildUnit(UnitTypeId.HATCHERY, 2),
        BuildUnit(UnitTypeId.DRONE, 16),
        BuildUnit(UnitTypeId.EXTRACTOR, 1),
        BuildUnit(UnitTypeId.SPAWNINGPOOL, 1),
    ]
)

HATCH_FIRST = BuildOrderChain(
    [
        BuildUnit(UnitTypeId.DRONE, 13),
        BuildUnit(UnitTypeId.OVERLORD, 2),
        BuildUnit(UnitTypeId.DRONE, 16),
        BuildUnit(UnitTypeId.HATCHERY, 2),
        BuildUnit(UnitTypeId.DRONE, 17),
        BuildUnit(UnitTypeId.EXTRACTOR, 1),
        BuildUnit(UnitTypeId.SPAWNINGPOOL, 1),
    ]
)
