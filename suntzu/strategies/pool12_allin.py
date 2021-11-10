
from typing import Union, Iterable, Dict, Set

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
        self.pack: Set[int] = set()

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

        # spend larva
        if bot.supply_cap <= bot.supply_used:
            if not bot.observation.planned_by_type[UnitTypeId.OVERLORD]:
                bot.add_macro_plan(MacroPlan(UnitTypeId.OVERLORD))
        elif bot.observation.count(UnitTypeId.DRONE) < worker_target:
            if not bot.observation.planned_by_type[UnitTypeId.DRONE]:
                bot.add_macro_plan(MacroPlan(UnitTypeId.DRONE))
        elif not bot.observation.planned_by_type[UnitTypeId.ZERGLING]:
            if not bot.observation.planned_by_type[UnitTypeId.ZERGLING]:
                bot.add_macro_plan(MacroPlan(UnitTypeId.ZERGLING))

        # spend bank
        elif bot.observation.count(UnitTypeId.QUEEN) < bot.observation.count(UnitTypeId.HATCHERY, include_planned=False):
            bot.add_macro_plan(MacroPlan(UnitTypeId.QUEEN))
        elif not bot.observation.planned_by_type[UnitTypeId.HATCHERY]:
            bot.add_macro_plan(MacroPlan(UnitTypeId.HATCHERY, priority=-1))

        for ling in bot.observation.actual_by_type[UnitTypeId.ZERGLING]:
            if ling.is_idle:
                self.pack.add(ling.tag)

        if 6 <= len(self.pack):
            for tag in self.pack:
                ling = bot.observation.unit_by_tag.get(tag)
                if ling:
                    ling.attack(bot.enemy_start_locations[0])
            self.pack.clear()

    def gas_target(self, bot) -> int:
        if bot.observation.count(UpgradeId.ZERGLINGMOVEMENTSPEED, include_planned=False):
            return 0
        elif 96 <= bot.vespene:
            return 0
        else:
            return 3

    def steps(self, bot):
        return {
            bot.update_observation: 1,
            bot.update_bases: 1,
            bot.update_gas: 1,
            bot.manage_queens: 1,
            bot.macro: 1,
            bot.update_strategy: 1,
        }