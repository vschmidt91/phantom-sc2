import logging
import math
from typing import Dict, Set

from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId

from .ai_base import AIBase
from .constants import SUPPLY_PROVIDED

SPORE_TRIGGERS: Dict[Race, Set[UnitTypeId]] = {
    Race.Zerg: {
        UnitTypeId.DRONEBURROWED,
        UnitTypeId.QUEENBURROWED,
        UnitTypeId.ZERGLINGBURROWED,
        UnitTypeId.BANELINGBURROWED,
        UnitTypeId.ROACHBURROWED,
        UnitTypeId.RAVAGERBURROWED,
        UnitTypeId.HYDRALISKBURROWED,
        UnitTypeId.LURKERMP,
        UnitTypeId.LURKERMPBURROWED,
        UnitTypeId.INFESTORBURROWED,
        UnitTypeId.SWARMHOSTBURROWEDMP,
        UnitTypeId.ULTRALISKBURROWED,
        UnitTypeId.MUTALISK,
        UnitTypeId.SPIRE,
    },
    Race.Protoss: {
        UnitTypeId.STARGATE,
        UnitTypeId.ORACLE,
        UnitTypeId.VOIDRAY,
        UnitTypeId.CARRIER,
        UnitTypeId.TEMPEST,
        UnitTypeId.PHOENIX,
    },
    Race.Terran: {
        UnitTypeId.STARPORT,
        UnitTypeId.STARPORTFLYING,
        UnitTypeId.MEDIVAC,
        UnitTypeId.LIBERATOR,
        UnitTypeId.RAVEN,
        UnitTypeId.BANSHEE,
        UnitTypeId.BATTLECRUISER,
        UnitTypeId.WIDOWMINE,
        UnitTypeId.WIDOWMINEBURROWED,
    },
}
SPORE_TRIGGERS[Race.Random] = {
    *SPORE_TRIGGERS[Race.Terran],
    *SPORE_TRIGGERS[Race.Protoss],
    *SPORE_TRIGGERS[Race.Zerg],
}


class ZergAI(AIBase):
    async def on_step(self, iteration):
        await super().on_step(iteration)

        self.morph_overlords()
        self.expand()

    def morph_overlords(self) -> None:
        supply_pending = sum(
            provided
            for unit_type, provided in SUPPLY_PROVIDED[self.race].items()
            for unit in self.unit_manager.pending_by_type[unit_type]
        )
        supply_planned = sum(
            provided
            for unit_type, provided in SUPPLY_PROVIDED[self.race].items()
            for plan in self.macro.planned_by_type(unit_type)
        )

        if 200 <= self.supply_cap + supply_pending + supply_planned:
            return

        supply_buffer = 4.0 + self.resource_manager.income.larva / 2.0

        if self.supply_left + supply_pending + supply_planned <= supply_buffer:
            plan = self.macro.add_plan(UnitTypeId.OVERLORD)
            plan.priority = 1

    def expand(self) -> None:
        # if self.count(UnitTypeId.SPAWNINGPOOL, include_pending=False, include_planned=False) < 1:
        #     return

        if self.time < 50:
            return

        worker_max = self.get_max_harvester()
        saturation = self.state.score.food_used_economy / max(1, worker_max)
        saturation = max(0, min(1, saturation))
        priority = 3 * (saturation - 1)

        expand = True
        if self.townhalls.amount == 2:
            expand = 21 <= self.state.score.food_used_economy
        elif 2 < self.townhalls.amount:
            expand = 2 / 3 < saturation

        for plan in self.macro.planned_by_type(UnitTypeId.HATCHERY):
            if plan.priority < math.inf:
                plan.priority = priority

        if expand and self.count(UnitTypeId.HATCHERY, include_actual=False) < 1:
            logging.info("%s: expanding", self.time_formatted)
            plan = self.macro.add_plan(UnitTypeId.HATCHERY)
            plan.priority = priority
            plan.max_distance = None
