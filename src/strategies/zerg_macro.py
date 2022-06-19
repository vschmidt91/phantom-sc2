
from __future__ import annotations
import math
import numpy as np
from typing import Counter, Union, Iterable, Dict, TYPE_CHECKING
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.game_data import UpgradeData

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.data import Race

from ..unit_counters import UNIT_COUNTER_DICT
from ..constants import ZERG_ARMOR_UPGRADES, ZERG_FLYER_ARMOR_UPGRADES, ZERG_FLYER_UPGRADES, ZERG_MELEE_UPGRADES, ZERG_RANGED_UPGRADES
from .strategy import Strategy

if TYPE_CHECKING:
    from ..ai_base import AIBase

class ZergMacro(Strategy):

    def __init__(self, ai: AIBase):
        super().__init__(ai)

    async def on_step(self) -> None:
        if self.ai.iteration % 10 == 0:
            self.update_composition()

    def update_composition(self) -> None:

        worker_count = self.ai.state.score.food_used_economy
        worker_target = np.clip(self.ai.get_max_harvester(), 1, 100)
        
        ratio = max(
            self.ai.combat.threat_level,
            # 1 if worker_count == worker_target else 0,
            worker_count / worker_target,
        )
        # ratio = self.ai.threat_level

        larva_rate = self.ai.macro.future_spending.larva / (60 * max(1, self.ai.macro.future_timeframe))
        larva_rate = max(0.0, larva_rate - self.ai.townhalls.ready.amount / 11.0)
        queen_target = math.ceil(larva_rate / (3/29))
        queen_target = min(queen_target, self.ai.townhalls.amount)
        queen_target = np.clip(1 + queen_target, 2, 8)
        # print(queen_target)

        # queen_target = min(8, 1 + self.ai.townhalls.amount)

        composition = {
            UnitTypeId.DRONE: worker_target,
            UnitTypeId.QUEEN: queen_target,
            UnitTypeId.ZERGLING: 0.0,
            UnitTypeId.ROACH: 0.0,
            UnitTypeId.RAVAGER: 0.0,
            UnitTypeId.HYDRALISK: 0.0,
            UnitTypeId.BROODLORD: 0.0,
            UnitTypeId.CORRUPTOR: 0.0,
        }

        can_build = {
            t: not any(self.ai.get_missing_requirements(t))
            for t in composition
        }

        enemy_counts = Counter(
            enemy.unit.type_id
            for enemy in self.ai.unit_manager.enemies.values()
            if enemy.unit
        )

        if any(enemy_counts):
            for enemy_type, count in enemy_counts.items():
                if counters := UNIT_COUNTER_DICT.get(enemy_type):
                    for t in counters:
                        if can_build[t]:
                            composition[t] += max(1, 2 * ratio) * count * self.ai.get_unit_cost(enemy_type) / self.ai.get_unit_cost(t)
                            break
        else:
            composition[UnitTypeId.ZERGLING] = 1.0


        composition[UnitTypeId.RAVAGER] += composition[UnitTypeId.ROACH] / 7
        composition[UnitTypeId.CORRUPTOR] += composition[UnitTypeId.BROODLORD] / 3

        tech_up = 30 <= worker_count and 3 <= self.ai.townhalls.amount

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

        self.ai.macro.composition = {
            k: math.ceil(v)
            for k, v in composition.items()
            if 0 < v
        }
        # self.ai.composition = { UnitTypeId.LAIR: 1 }


    def filter_upgrade(self, upgrade) -> bool:
        if upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL1:
            return 0 < self.ai.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL2, include_planned=False)
        elif upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL2:
            return 0 < self.ai.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL3, include_planned=False)
        elif upgrade in ZERG_FLYER_UPGRADES or upgrade in ZERG_FLYER_ARMOR_UPGRADES:
            return 0 < self.ai.count(UnitTypeId.GREATERSPIRE, include_planned=False)
        elif upgrade == UpgradeId.OVERLORDSPEED:
            return 8 * 60 < self.ai.time
        elif upgrade in { UpgradeId.BURROW, UpgradeId.TUNNELINGCLAWS }:
            return False
        else:
            return super().filter_upgrade(upgrade)