
from typing import Union, Iterable, Dict

from matplotlib.image import composite_images

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId

from .zerg_macro import ZergMacro
from .zerg_strategy import ZergStrategy
from ..modules.macro import MacroPlan

class Pool12(ZergMacro):

    def build_order(self) -> Iterable:
        return [
            UnitTypeId.SPAWNINGPOOL,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.OVERLORD,
            UnitTypeId.ZERGLING,
            UnitTypeId.ZERGLING,
            UnitTypeId.ZERGLING,
            UnitTypeId.QUEEN,
            MacroPlan(UnitTypeId.HATCHERY, max_distance=0),
            UnitTypeId.ZERGLING,
            UnitTypeId.ZERGLING,
            # UnitTypeId.OVERLORD,
            # UnitTypeId.QUEEN,
            # UnitTypeId.ZERGLING,
            # UnitTypeId.ZERGLING,
            # UnitTypeId.DRONE,
            # UnitTypeId.OVERLORD,
        ]

    def filter_upgrade(self, upgrade) -> bool:
        if self.ai.time < 2.5 * 60:
            return False
        return super().filter_upgrade(upgrade)

    def update(self) -> None:
        super().update()
        if UnitTypeId.ROACH in self.ai.composition and self.ai.time < 2.5 * 60:
            del self.ai.composition[UnitTypeId.ROACH]