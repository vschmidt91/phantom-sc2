
from typing import Union, Iterable, Dict

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId
from suntzu.macro_plan import MacroPlan

from .zerg_macro import ZergMacro
from .zerg_strategy import ZergStrategy

class DummyStrategy(ZergStrategy):

    def __init__(self):
        super().__init__()

    def build_order(self) -> Iterable[Union[UnitTypeId, UpgradeId]]:
        return []

    def composition(self, bot) -> Dict[UnitTypeId, int]:
        return {}

    def steps(self, bot):

        steps = {
            # bot.kill_random_unit: 100,
            bot.update_tables: 1,
            bot.update_maps: 1,
            bot.update_bases: 1,
            bot.draw_debug: 1,
        }

        return steps