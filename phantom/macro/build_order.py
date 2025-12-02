from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit

from phantom.common.action import Action, UseAbility
from phantom.macro.builder import MacroPlan

if TYPE_CHECKING:
    from phantom.main import PhantomBot


@dataclass(frozen=True)
class BuildOrderStep:
    plans: list[MacroPlan]
    actions: Mapping[Unit, Action]


class BuildOrder(ABC):
    @abstractmethod
    def execute(self, bot: "PhantomBot") -> BuildOrderStep | None:
        raise NotImplementedError()


@dataclass(frozen=True)
class Make(BuildOrder):
    unit: UnitTypeId
    target: int

    def execute(self, bot: "PhantomBot") -> BuildOrderStep | None:
        actual_or_pending = bot.count_actual(self.unit) + bot.count_pending(self.unit)
        if actual_or_pending >= self.target:
            return None
        deficit = self.target - actual_or_pending - bot.count_planned(self.unit)
        if deficit == 0:
            return BuildOrderStep([], {})
        plans = [MacroPlan(self.unit) for _ in range(deficit)]
        return BuildOrderStep(plans, {})


@dataclass(frozen=True)
class WaitUntil(BuildOrder):
    condition: Callable[["PhantomBot"], bool]

    def execute(self, bot: "PhantomBot") -> BuildOrderStep | None:
        if self.condition(bot):
            return None
        return BuildOrderStep([], {})


@dataclass(frozen=True)
class ExtractorTrick(BuildOrder):
    unit_type = UnitTypeId.EXTRACTOR
    at_supply = 14
    min_minerals = 40

    def execute(self, bot: "PhantomBot") -> BuildOrderStep | None:
        if bot.supply_used < self.at_supply:
            return BuildOrderStep([], {})
        if bot.supply_used == self.at_supply and bot.bank.supply <= 0:
            has_extractor = (
                bot.count_actual(self.unit_type) > 0
                or bot.count_pending(self.unit_type) > 0
                or bot.count_planned(self.unit_type) > 0
            )
            if not has_extractor:
                if self.min_minerals <= bot.bank.minerals:
                    return BuildOrderStep([MacroPlan(self.unit_type, priority=np.inf)], {})
                else:
                    return BuildOrderStep([], {})
            units = bot.structures(self.unit_type).not_ready
            return BuildOrderStep([], {u: UseAbility(AbilityId.CANCEL) for u in units})
        return None


@dataclass(frozen=True)
class BuildOrderChain(BuildOrder):
    steps: list[BuildOrder]

    def execute(self, bot: "PhantomBot") -> BuildOrderStep | None:
        for step in self.steps:
            if result := step.execute(bot):
                return result
        return None


BUILD_ORDERS = {
    "OVERHATCH": BuildOrderChain(
        [
            Make(UnitTypeId.DRONE, 14),
            ExtractorTrick(),
            Make(UnitTypeId.OVERLORD, 2),
            Make(UnitTypeId.HATCHERY, 2),
            Make(UnitTypeId.DRONE, 17),
            Make(UnitTypeId.EXTRACTOR, 1),
            WaitUntil(lambda bot: bot.gas_buildings),
            Make(UnitTypeId.SPAWNINGPOOL, 1),
            Make(UnitTypeId.DRONE, 20),
            WaitUntil(lambda bot: bot.structures(UnitTypeId.SPAWNINGPOOL).ready),
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
            WaitUntil(lambda bot: bot.gas_buildings),
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
            WaitUntil(lambda bot: bot.workers.amount > 16),
            Make(UnitTypeId.EXTRACTOR, 1),
            Make(UnitTypeId.SPAWNINGPOOL, 1),
            Make(UnitTypeId.HATCHERY, 3),
            Make(UnitTypeId.DRONE, 19),
            Make(UnitTypeId.QUEEN, 1),
            Make(UnitTypeId.ZERGLING, 1),
            Make(UnitTypeId.QUEEN, 2),
        ]
    ),
    "POOL_FIRST": BuildOrderChain(
        [
            Make(UnitTypeId.DRONE, 13),
            Make(UnitTypeId.OVERLORD, 2),
            Make(UnitTypeId.DRONE, 17),
            WaitUntil(lambda bot: bot.workers.amount > 14),
            Make(UnitTypeId.SPAWNINGPOOL, 1),
            Make(UnitTypeId.EXTRACTOR, 1),
            Make(UnitTypeId.DRONE, 18),
            Make(UnitTypeId.HATCHERY, 2),
            Make(UnitTypeId.QUEEN, 1),
            Make(UnitTypeId.ZERGLING, 2),
        ]
    ),
    "ROACH_RUSH": BuildOrderChain(
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
        ]
    ),
}
