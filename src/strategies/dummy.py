
from typing import Union, Iterable, Dict

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId
from ..macro_plan import MacroPlan

from .zerg_macro import ZergMacro
from .zerg_strategy import ZergStrategy

class DummyStrategy(ZergStrategy):

    def build_order(self) -> Iterable[Union[UnitTypeId, UpgradeId]]:
        return [
            UnitTypeId.EXTRACTOR,
            UnitTypeId.EXTRACTOR,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
        ]


    def update(self):
        self.ai.scout_manager.scout_enemy_natural = False
        if 6720 <= self.ai.state.game_loop:
            print(self.ai.state.score.collected_vespene)
        return super().update()