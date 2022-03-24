
from typing import Union, Iterable, Dict

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId

from ..macro_plan import MacroPlan
from .zerg_macro import ZergMacro
from .zerg_strategy import ZergStrategy

class RoachRush(ZergMacro):

    def build_order(self) -> Iterable:
        return [
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.OVERLORD,
            UnitTypeId.SPAWNINGPOOL,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.EXTRACTOR,
            MacroPlan(UnitTypeId.HATCHERY, max_distance=0),
            UnitTypeId.QUEEN,
            UnitTypeId.ZERGLING,
            UnitTypeId.ZERGLING,
            UnitTypeId.ROACHWARREN,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.OVERLORD,
            UnitTypeId.ROACH,
            UnitTypeId.ROACH,
            UnitTypeId.ROACH,
            UnitTypeId.ROACH,
            UnitTypeId.ROACH,
            UnitTypeId.ROACH,
            UnitTypeId.ROACH,
            # MacroPlan(UnitTypeId.HATCHERY, max_distance=0),
        ]

    def filter_upgrade(self, upgrade: UpgradeId) -> bool:
        if self.ai.time < 200:
            return False
        return super().filter_upgrade(upgrade)

    def update(self):
        self.ai.scout_manager.scout_enemy_natural = False
        if self.ai.time < 200 and UnitTypeId.ZERGLING in self.ai.composition:
            del self.ai.composition[UnitTypeId.ZERGLING]
        return super().update()