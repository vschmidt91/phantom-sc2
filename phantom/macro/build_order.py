from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import numpy as np
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit

from phantom.common.action import Action, UseAbility
from phantom.macro.main import MacroPlan
from phantom.observation import Observation


@dataclass(frozen=True)
class BuildOrderStep:
    plans: list[MacroPlan]
    actions: Mapping[Unit, Action]


class BuildOrder(ABC):
    @abstractmethod
    def execute(self, obs: Observation) -> BuildOrderStep | None:
        raise NotImplementedError()


@dataclass(frozen=True)
class Make(BuildOrder):
    unit: UnitTypeId
    target: int

    def execute(self, obs: Observation) -> BuildOrderStep | None:
        actual_or_pending = obs.count_actual(self.unit) + obs.count_pending(self.unit)
        if actual_or_pending >= self.target:
            return None
        deficit = self.target - actual_or_pending - obs.count_planned(self.unit)
        plans = [MacroPlan(self.unit) for _ in range(deficit)]
        return BuildOrderStep(plans, {})


@dataclass(frozen=True)
class WaitUntil(BuildOrder):
    condition: Callable[[Observation], bool]

    def execute(self, obs: Observation) -> BuildOrderStep | None:
        if self.condition(obs):
            return None
        return BuildOrderStep([], {})


@dataclass(frozen=True)
class ExtractorTrick(BuildOrder):
    unit_type = UnitTypeId.EXTRACTOR
    at_supply = 14
    min_minerals = 50

    def execute(self, obs: Observation) -> BuildOrderStep | None:
        if self.at_supply == obs.supply_used and obs.bank.supply <= 0:
            has_extractor = any(
                (
                    obs.count_actual(self.unit_type),
                    obs.count_pending(self.unit_type),
                    obs.count_planned(self.unit_type),
                )
            )
            if not has_extractor:
                if self.min_minerals < obs.bank.minerals:
                    return BuildOrderStep([MacroPlan(self.unit_type, priority=np.inf)], {})
                else:
                    return BuildOrderStep([], {})
            units = obs.structures(self.unit_type).not_ready
            return BuildOrderStep([], {u: UseAbility(AbilityId.CANCEL) for u in units})
        return None


@dataclass(frozen=True)
class BuildOrderChain(BuildOrder):
    steps: list[BuildOrder]

    def execute(self, obs: Observation) -> BuildOrderStep | None:
        for step in self.steps:
            if result := step.execute(obs):
                return result
        return None


BUILD_ORDERS = {
    "OVERHATCH": BuildOrderChain(
        [
            Make(UnitTypeId.DRONE, 14),
            ExtractorTrick(),
            Make(UnitTypeId.OVERLORD, 2),
            Make(UnitTypeId.HATCHERY, 2),
            Make(UnitTypeId.DRONE, 16),
            Make(UnitTypeId.SPAWNINGPOOL, 1),
            Make(UnitTypeId.EXTRACTOR, 1),
        ]
    ),
    "HATCH_FIRST": BuildOrderChain(
        [
            Make(UnitTypeId.DRONE, 13),
            Make(UnitTypeId.OVERLORD, 2),
            Make(UnitTypeId.DRONE, 16),
            Make(UnitTypeId.HATCHERY, 2),
            Make(UnitTypeId.DRONE, 17),
            Make(UnitTypeId.EXTRACTOR, 1),
            WaitUntil(lambda obs: obs.gas_buildings),
            Make(UnitTypeId.SPAWNINGPOOL, 1),
        ]
    ),
    "HATCH_POOL_HATCH": BuildOrderChain(
        [
            Make(UnitTypeId.DRONE, 13),
            Make(UnitTypeId.OVERLORD, 2),
            Make(UnitTypeId.DRONE, 17),
            Make(UnitTypeId.HATCHERY, 2),
            Make(UnitTypeId.DRONE, 18),
            WaitUntil(lambda obs: obs.workers.amount > 16),
            Make(UnitTypeId.EXTRACTOR, 1),
            # WaitUntil(lambda obs: obs.gas_buildings),
            Make(UnitTypeId.SPAWNINGPOOL, 1),
            # WaitUntil(lambda obs: obs.structures(UnitTypeId.SPAWNINGPOOL)),
            Make(UnitTypeId.HATCHERY, 3),
            Make(UnitTypeId.DRONE, 19),
            Make(UnitTypeId.QUEEN, 1),
            Make(UnitTypeId.ZERGLING, 1),
            Make(UnitTypeId.QUEEN, 2),
            # WaitUntil(lambda obs: obs.supply_used >= 24),
        ]
    ),
    "POOL_FIRST": BuildOrderChain(
        [
            Make(UnitTypeId.DRONE, 14),
            Make(UnitTypeId.OVERLORD, 2),
            Make(UnitTypeId.SPAWNINGPOOL, 1),
            Make(UnitTypeId.DRONE, 17),
            Make(UnitTypeId.HATCHERY, 2),
            Make(UnitTypeId.QUEEN, 1),
            Make(UnitTypeId.ZERGLING, 1),
            Make(UnitTypeId.EXTRACTOR, 1),
            Make(UnitTypeId.ROACHWARREN, 1),
            # Make(UnitTypeId.DRONE, 19),
            # Make(UnitTypeId.ROACHWARREN, 1),
            # Make(UnitTypeId.OVERLORD, 3),
            # Make(UnitTypeId.ROACH, 7),
        ]
    ),
    "TEST": BuildOrderChain(
        [
            Make(UnitTypeId.DRONE, 14),
            Make(UnitTypeId.OVERLORD, 2),
            Make(UnitTypeId.SPAWNINGPOOL, 1),
            Make(UnitTypeId.DRONE, 17),
            Make(UnitTypeId.HATCHERY, 2),
            Make(UnitTypeId.QUEEN, 1),
        ]
    ),
}
