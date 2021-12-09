
from typing import Union, Iterable, Dict, Set

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId
from ..constants import SUPPLY_PROVIDED

from .zerg_macro import ZergMacro
from .zerg_strategy import ZergStrategy
from ..macro_plan import MacroPlan

class Pool12AllIn(ZergStrategy):

    def __init__(self, pull_workers: bool = False):
        super().__init__()
        self.pull_workers: bool = pull_workers

    def build_order(self) -> Iterable[Union[UnitTypeId, UpgradeId]]:
        if self.pull_workers:
            return [
                UnitTypeId.SPAWNINGPOOL,
                UnitTypeId.DRONE,
                UnitTypeId.DRONE,
                UnitTypeId.DRONE,
                UnitTypeId.OVERLORD,
                UnitTypeId.ZERGLING,
                UnitTypeId.ZERGLING,
                UnitTypeId.ZERGLING,
            ]
        else:
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
            if not bot.count(UnitTypeId.OVERLORD, include_actual=False):
                bot.add_macro_plan(MacroPlan(UnitTypeId.OVERLORD))
        elif bot.count(UnitTypeId.DRONE) < worker_target:
            if not bot.planned_by_type[UnitTypeId.DRONE]:
                bot.add_macro_plan(MacroPlan(UnitTypeId.DRONE))
        elif not bot.planned_by_type[UnitTypeId.ZERGLING]:
            bot.add_macro_plan(MacroPlan(UnitTypeId.ZERGLING))
        elif self.pull_workers:
            pass

        # spend bank
        elif bot.count(UnitTypeId.QUEEN) < bot.count(UnitTypeId.HATCHERY, include_planned=False):
            bot.add_macro_plan(MacroPlan(UnitTypeId.QUEEN))
        elif not bot.planned_by_type[UnitTypeId.HATCHERY]:
            bot.add_macro_plan(MacroPlan(UnitTypeId.HATCHERY, priority=-1))

        for ling in bot.actual_by_type[UnitTypeId.ZERGLING]:
            if ling.is_idle:
                ling.attack(bot.enemy_start_locations[0])

        if self.pull_workers and bot.count(UnitTypeId.ZERGLING, include_planned=False, include_pending=False):
            while True:
                worker = bot.bases.try_remove_any()
                if worker:
                    bot.unit_by_tag[worker].attack(bot.enemy_start_locations[0])
                    bot.drafted_civilians.add(worker)
                else:
                    break

        for worker in bot.workers:
            bot.worker_behavior.execute(worker)

    def gas_target(self, bot) -> int:
        if self.pull_workers:
            return 0
        elif bot.count(UpgradeId.ZERGLINGMOVEMENTSPEED, include_planned=False):
            return 0
        elif 96 <= bot.vespene:
            return 0
        else:
            return 3

    def steps(self, bot):
        return {
            bot.update_tables: 1,
            bot.handle_errors: 1,
            bot.handle_actions: 1,
            bot.update_bases: 1,
            bot.update_gas: 1,
            bot.manage_queens: 1,
            bot.macro: 1,
            bot.update_strategy: 1,
            bot.assign_idle_workers: 1,
        }