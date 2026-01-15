from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ares.consts import ALL_WORKER_TYPES
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit

from phantom.common.action import Action, UseAbility
from phantom.common.utils import MacroId
from phantom.macro.builder import MacroPlan

if TYPE_CHECKING:
    from phantom.main import PhantomBot


@dataclass(frozen=True)
class BuildOrderStep:
    plans: Mapping[UnitTypeId, MacroPlan] = field(default_factory=dict)
    priorities: Mapping[MacroId, float] = field(default_factory=dict)
    actions: Mapping[Unit, Action] = field(default_factory=dict)


class BuildOrder(ABC):
    @abstractmethod
    def execute(self, bot: "PhantomBot") -> BuildOrderStep | None:
        raise NotImplementedError()


@dataclass(frozen=True)
class Make(BuildOrder):
    unit: UnitTypeId
    target: int

    def execute(self, bot: "PhantomBot") -> BuildOrderStep | None:
        needs_planning = not UNIT_TRAINED_FROM.get(self.unit, set()).isdisjoint(ALL_WORKER_TYPES)
        count = bot.count_actual(self.unit) + bot.count_pending(self.unit)
        if count >= self.target:
            return None
        if needs_planning and count + bot.count_planned(self.unit) >= self.target:
            return BuildOrderStep()
        if needs_planning:
            return BuildOrderStep(plans={self.unit: MacroPlan()})
        else:
            return BuildOrderStep(priorities={self.unit: 0.0})


@dataclass(frozen=True)
class Until(BuildOrder):
    condition: Callable[["PhantomBot"], bool]
    step: BuildOrder

    def execute(self, bot: "PhantomBot") -> BuildOrderStep | None:
        return None if self.condition(bot) else self.step.execute(bot)


@dataclass(frozen=True)
class Wait(BuildOrder):
    def execute(self, bot: "PhantomBot") -> BuildOrderStep | None:
        return BuildOrderStep()


@dataclass(frozen=True)
class ExtractorTrick(BuildOrder):
    unit_type = UnitTypeId.EXTRACTOR
    at_supply = 14
    min_minerals = 50

    def execute(self, bot: "PhantomBot") -> BuildOrderStep | None:
        if bot.supply_used < self.at_supply:
            return BuildOrderStep()
        if bot.count_pending(UnitTypeId.OVERLORD):
            return None
        if bot.supply_used == self.at_supply and bot.bank.supply <= 0:
            has_extractor = (
                bot.count_actual(self.unit_type) > 0
                or bot.count_pending(self.unit_type) > 0
                or bot.count_planned(self.unit_type) > 0
            )
            if not has_extractor:
                if self.min_minerals <= bot.bank.minerals:
                    return BuildOrderStep(plans={self.unit_type: MacroPlan()})
                else:
                    return BuildOrderStep()
            units = bot.structures(self.unit_type).not_ready
            return BuildOrderStep(actions={u: UseAbility(AbilityId.CANCEL) for u in units})
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
            Until(lambda bot: bot.gas_buildings, Wait()),
            Make(UnitTypeId.SPAWNINGPOOL, 1),
            Make(UnitTypeId.DRONE, 20),
            Until(lambda bot: bot.structures(UnitTypeId.SPAWNINGPOOL).ready, Wait()),
        ]
    ),
    "OVERPOOL": BuildOrderChain(
        [
            Make(UnitTypeId.DRONE, 14),
            Until(lambda bot: bot.structures(UnitTypeId.SPAWNINGPOOL), ExtractorTrick()),
            Make(UnitTypeId.OVERLORD, 2),
            Make(UnitTypeId.SPAWNINGPOOL, 1),
            Make(UnitTypeId.DRONE, 18),
            # Until(lambda bot: bot.townhalls.amount > 1, Make(UnitTypeId.DRONE, 18)),
            # Until(lambda bot: bot.townhalls.amount > 1 or bot.workers.amount > 16, Wait()),
            # Make(UnitTypeId.HATCHERY, 2),
            # Until(lambda bot: bot.townhalls.amount > 1, Wait()),
            # Make(UnitTypeId.EXTRACTOR, 1),
            # Make(UnitTypeId.QUEEN, 1),
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
            Until(lambda bot: bot.gas_buildings, Wait()),
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
            Until(lambda bot: bot.workers.amount > 16, Wait()),
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
            Until(lambda bot: bot.workers.amount > 14, Wait()),
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
