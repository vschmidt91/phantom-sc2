
from typing import Union, Iterable, Dict

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId
from ..macro_plan import MacroPlan

from .zerg_macro import ZergMacro
from .zerg_strategy import ZergStrategy

class GasLess(ZergStrategy):

    def __init__(self):
        super().__init__()

    def build_order(self) -> Iterable[Union[UnitTypeId, UpgradeId]]:
        return [
            UnitTypeId.DRONE,
            UnitTypeId.OVERLORD,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.HATCHERY,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.EXTRACTOR,
            UnitTypeId.SPAWNINGPOOL,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.OVERLORD,
            UnitTypeId.QUEEN,
            UnitTypeId.QUEEN,
            UnitTypeId.ZERGLING,
            UnitTypeId.ZERGLING,
            UpgradeId.ZERGLINGMOVEMENTSPEED,
        ]

    def update(self) -> None:
        self.ai.destroy_destructables = 4 * 60 < self.ai.time
        if self.ai.time < 4 * 60:
            self.ai.composition = {
                UnitTypeId.DRONE: 66,
                UnitTypeId.QUEEN: 4,
            }
        else:
            self.ai.composition = {
                UnitTypeId.DRONE: 66,
                UnitTypeId.QUEEN: 80,
                UnitTypeId.ZERGLING: 80,
                UnitTypeId.BANELING: 80,
            }