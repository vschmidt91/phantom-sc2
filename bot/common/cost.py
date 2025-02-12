import math
from dataclasses import dataclass
from functools import cached_property
from typing import Callable

import numpy as np
from sc2.game_data import Cost as SC2Cost
from sc2.ids.unit_typeid import UnitTypeId

from bot.common.constants import LARVA_COST
from bot.common.main import BotBase, MacroId
from bot.common.unit_composition import UnitComposition

MineralVespeneCostProvider = Callable[[UnitTypeId], SC2Cost]
SupplyCostProvider = Callable[[UnitTypeId], float]


@dataclass(frozen=True)
class Cost:
    minerals: float
    vespene: float
    supply: float
    larva: float

    def __add__(self, other: "Cost"):
        return Cost(
            self.minerals + other.minerals,
            self.vespene + other.vespene,
            self.supply + other.supply,
            self.larva + other.larva,
        )

    def __sub__(self, other: "Cost"):
        return Cost(
            self.minerals - other.minerals,
            self.vespene - other.vespene,
            self.supply - other.supply,
            self.larva - other.larva,
        )

    def __truediv__(self, other: "Cost"):
        return Cost(
            self.minerals / other.minerals if other.minerals != 0.0 else math.inf,
            self.vespene / other.vespene if other.vespene != 0.0 else math.inf,
            self.supply / other.supply if other.supply != 0.0 else math.inf,
            self.larva / other.larva if other.larva != 0.0 else math.inf,
        )

    @cached_property
    def total_resources(self) -> float:
        return self.minerals + self.vespene

    @cached_property
    def sign(self) -> "Cost":
        return Cost(
            np.sign(self.minerals),
            np.sign(self.vespene),
            np.sign(self.supply),
            np.sign(self.larva),
        )

    @classmethod
    def max(cls, a: "Cost", b: "Cost") -> "Cost":
        return Cost(
            max(a.minerals, b.minerals),
            max(a.vespene, b.vespene),
            max(a.supply, b.supply),
            max(a.larva, b.larva),
        )

    def __mul__(self, factor: float):
        return Cost(self.minerals * factor, self.vespene * factor, self.supply * factor, self.larva * factor)

    def __repr__(self) -> str:
        return f"Cost({self.minerals}M, {self.vespene}G, {self.supply}F, {self.larva}L)"


@dataclass
class CostManager:

    bot: BotBase
    _cache = dict[MacroId, Cost]()

    @cached_property
    def zero(self) -> Cost:
        return Cost(0, 0, 0, 0)

    def of(self, item: MacroId) -> Cost:
        if cached := self._cache.get(item):
            return cached
        try:
            cost = self.bot.calculate_cost(item)
            supply = self.bot.calculate_supply_cost(item)
        except Exception:
            return self.zero
        larva = LARVA_COST.get(item, 0.0)
        cost = Cost(float(cost.minerals), float(cost.vespene), supply, larva)
        self._cache[item] = cost
        return cost

    def of_composition(self, composition: UnitComposition) -> Cost:
        return sum(
            (self.of(k) * v for k, v in composition.items()),
            self.zero,
        )
