
from __future__ import annotations
import math
from typing import Union, Iterable, Dict, TYPE_CHECKING
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.game_data import UpgradeData

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.data import Race

from ..unit_counters import UNIT_COUNTER_DICT
from ..constants import BUILD_ORDER_PRIORITY, ZERG_ARMOR_UPGRADES, ZERG_FLYER_ARMOR_UPGRADES, ZERG_FLYER_UPGRADES, ZERG_MELEE_UPGRADES, ZERG_RANGED_UPGRADES
from ..cost import Cost
from ..macro_plan import MacroPlan
from ..utils import unitValue
from .zerg_strategy import ZergStrategy

from ..ai_base import AIBase

class ZergMacro(ZergStrategy):

    def __init__(self, ai: AIBase):
        super().__init__(ai)

    def update(self) -> None:

        self.ai.destroy_destructables = 5 * 60 < self.ai.time

        worker_count = self.ai.state.score.food_used_economy
        worker_target = max(1, min(80, self.ai.get_max_harvester()))
        # ratio = max(
        #     self.ai.threat_level,
        #     worker_count / worker_target,
        # )
        ratio = self.ai.threat_level

        queen_target = min(8, 2 * self.ai.townhalls.amount)

        composition = {
            UnitTypeId.DRONE: worker_target,
            UnitTypeId.QUEEN: queen_target,
            UnitTypeId.ZERGLING: 1.0,
            UnitTypeId.ROACH: 0.0,
            UnitTypeId.HYDRALISK: 0.0,
            UnitTypeId.BROODLORD: 0.0,
            UnitTypeId.CORRUPTOR: 0.0,
        }

        can_build = {
            t: not any(self.ai.get_missing_requirements(t, include_pending=False, include_planned=False))
            for t in composition
        }

        for enemy in self.ai.enumerate_enemies():
            if counters := UNIT_COUNTER_DICT.get(enemy.type_id):
                for t in counters:
                    if can_build[t]:
                        count = self.ai.get_unit_cost(enemy.type_id) / self.ai.get_unit_cost(t)
                        # composition[t] += (ratio + 1 - self.ai.map_data.distance[enemy.position.rounded]) * count
                        composition[t] += 2 * ratio * count
                        break


        tech_up = 32 <= worker_count and 3 <= self.ai.townhalls.amount

        if tech_up and UpgradeId.ZERGLINGMOVEMENTSPEED in self.ai.state.upgrades:
            composition[UnitTypeId.ROACHWARREN] = 1
            composition[UnitTypeId.OVERSEER] = 1

        if tech_up and self.ai.count(UnitTypeId.LAIR, include_pending=False, include_planned=False) + self.ai.count(UnitTypeId.HIVE, include_pending=False, include_planned=False):
            composition[UnitTypeId.HYDRALISKDEN] = 1
            composition[UnitTypeId.OVERSEER] = 2
            composition[UnitTypeId.EVOLUTIONCHAMBER] = 2

        if tech_up and self.ai.count(UnitTypeId.HIVE, include_pending=False, include_planned=False):
            composition[UnitTypeId.GREATERSPIRE] = 1
            composition[UnitTypeId.OVERSEER] = 3

        self.ai.composition = { k: math.ceil(v) for k, v in composition.items() if 0 < v}

    def filter_upgrade(self, upgrade) -> bool:
        if upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL1:
            return 0 < self.ai.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL2, include_planned=False)
        elif upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL2:
            return 0 < self.ai.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL3, include_planned=False)
        elif upgrade in ZERG_FLYER_UPGRADES or upgrade in ZERG_FLYER_ARMOR_UPGRADES:
            return 0 < self.ai.count(UnitTypeId.GREATERSPIRE, include_planned=False)
        elif upgrade == UpgradeId.OVERLORDSPEED:
            return 8 * 60 < self.ai.time
        return super().filter_upgrade(upgrade)