from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

from loguru import logger
from sc2.game_data import Cost as SC2Cost
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from .constants import LARVA_COST

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

    def __mul__(self, factor: float):
        return Cost(self.minerals * factor, self.vespene * factor, self.supply * factor, self.larva * factor)

    def __repr__(self) -> str:
        return f"Cost({self.minerals}M, {self.vespene}G, {self.supply}F, {self.larva}L)"


class CostManager:

    def __init__(self, mineral_vespene: MineralVespeneCostProvider, supply: SupplyCostProvider):
        self.mineral_vespene = mineral_vespene
        self.supply = supply

    @lru_cache(maxsize=None)
    def of(self, item: UnitTypeId | UpgradeId) -> Cost:
        try:
            cost = self.mineral_vespene(item)
            supply = self.supply(item)
        except Exception:
            logger.info(f"Failed to calculate cost for {item}")
            return Cost(0.0, 0.0, 0.0, 0.0)
        larva = LARVA_COST.get(item, 0.0)
        return Cost(float(cost.minerals), float(cost.vespene), supply, larva)
