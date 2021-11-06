
from typing import Union, Iterable, Dict

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId
from suntzu.constants import SUPPLY_PROVIDED

from .zerg_macro import ZergMacro
from .zerg_strategy import ZergStrategy
from ..observation import Observation
from ..macro_plan import MacroPlan

class Pool12AllIn(ZergStrategy):

    def __init__(self):
        super().__init__()

    def build_order(self) -> Iterable[Union[UnitTypeId, UpgradeId]]:
        return [
            UnitTypeId.SPAWNINGPOOL,
            UnitTypeId.DRONE,
            UnitTypeId.EXTRACTOR,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.OVERLORD,
            UnitTypeId.ZERGLING,
            UnitTypeId.ZERGLING,
            UnitTypeId.ZERGLING,
            UnitTypeId.QUEEN,
            UnitTypeId.ZERGLING,
            UnitTypeId.ZERGLING,
            UpgradeId.ZERGLINGMOVEMENTSPEED
        ]

    def update(self, bot):
        worker_target = 11 * bot.townhalls.ready.amount
        food_planned = sum(bot.cost[plan.item].food for plan in bot.macro_plans)
        supply_planned = sum(n * bot.observation.count(t, include_actual=False) for t, n in SUPPLY_PROVIDED.items())
        if bot.observation.count(UnitTypeId.DRONE) < worker_target:
            bot.add_macro_plan(MacroPlan(UnitTypeId.DRONE))
        if not bot.observation.count(UnitTypeId.ZERGLING, include_actual=False, include_pending=False):
            bot.add_macro_plan(MacroPlan(UnitTypeId.ZERGLING))
        if bot.observation.count(UnitTypeId.QUEEN) < bot.townhalls.amount:
            bot.add_macro_plan(MacroPlan(UnitTypeId.QUEEN))
        if bot.supply_cap + supply_planned < bot.supply_used + food_planned:
            bot.add_macro_plan(MacroPlan(UnitTypeId.OVERLORD))
        if 300 <= bot.minerals:
            if not bot.observation.count(UnitTypeId.HATCHERY, include_actual=False):
                bot.add_macro_plan(MacroPlan(UnitTypeId.HATCHERY))

    def gas_target(self, bot) -> int:
        if bot.observation.count(UpgradeId.ZERGLINGMOVEMENTSPEED, include_planned=False):
            return 0
        elif 96 <= bot.vespene:
            return 0
        else:
            return 3