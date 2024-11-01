import math
from abc import ABC
from typing import Counter

import numpy as np
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from ..constants import (
    UNIT_COUNTER_DICT,
    ZERG_FLYER_ARMOR_UPGRADES,
    ZERG_FLYER_UPGRADES,
)
from .base import Component


class Strategy(Component, ABC):
    _tech_up = False

    def update_composition(self, worker_target: int, confidence: float) -> dict[UnitTypeId, int]:

        worker_count = self.state.score.food_used_economy

        ratio = max(
            1 - confidence,
            worker_count / worker_target,
        )
        queen_target = 1 + self.townhalls.amount
        queen_target = np.clip(queen_target, 0, 12)

        composition = {
            UnitTypeId.DRONE: worker_target,
            UnitTypeId.QUEEN: queen_target,
            UnitTypeId.ZERGLING: 0.0,
            UnitTypeId.ROACH: 0.0,
            UnitTypeId.RAVAGER: 0.0,
            UnitTypeId.HYDRALISK: 0.0,
            UnitTypeId.BROODLORD: 0.0,
            UnitTypeId.CORRUPTOR: 0.0,
            UnitTypeId.MUTALISK: 0.0,
        }

        can_build = {t: not any(self.get_missing_requirements(t)) for t in composition}

        enemy_counts = Counter[UnitTypeId](
            enemy.type_id for enemy in self.all_enemy_units if enemy.type_id in UNIT_COUNTER_DICT
        )

        self._tech_up = 35 <= worker_count and 3 <= self.townhalls.amount
        lair_count = self.count(UnitTypeId.LAIR, include_pending=False, include_planned=False)
        hive_count = self.count(UnitTypeId.HIVE, include_pending=True, include_planned=False)

        def total_cost(t: UnitTypeId) -> float:
            c = self.cost.of(t)
            return c.minerals + c.vespene

        if any(enemy_counts):
            for enemy_type, count in enemy_counts.items():
                for counter in UNIT_COUNTER_DICT.get(enemy_type, []):
                    if can_build[counter]:
                        composition[counter] += 2.5 * ratio * count * total_cost(enemy_type) / total_cost(counter)
                        break
        elif 0.8 < self.tech_requirement_progress(UnitTypeId.ZERGLING):
            composition[UnitTypeId.ZERGLING] = 1.0

        composition[UnitTypeId.RAVAGER] += composition[UnitTypeId.ROACH] / 13
        composition[UnitTypeId.CORRUPTOR] += composition[UnitTypeId.BROODLORD] / 8

        if self._tech_up:
            composition[UnitTypeId.ROACHWARREN] = 1
            composition[UnitTypeId.OVERSEER] = 1

        if self._tech_up and 0 < lair_count + hive_count and 150 < self.supply_used:
            composition[UnitTypeId.HYDRALISKDEN] = 1
            composition[UnitTypeId.OVERSEER] = 2
            composition[UnitTypeId.EVOLUTIONCHAMBER] = 2

        if self._tech_up and 0 < hive_count and 150 < self.supply_used:
            if 0 == self.count(UnitTypeId.SPIRE, include_planned=False) + self.count(
                UnitTypeId.SPIRE, include_planned=False
            ):
                composition[UnitTypeId.SPIRE] = 1
            else:
                composition[UnitTypeId.GREATERSPIRE] = 1
            composition[UnitTypeId.OVERSEER] = 3

        if worker_count == worker_target:
            banking_minerals = max(0, self.minerals - 300)
            banking_gas = max(0, self.minerals - 300)
            if 0 < banking_minerals and 0 < banking_gas:
                composition[UnitTypeId.ZERGLING] += 24

                if 0 < banking_gas:
                    if 0 < hive_count:
                        composition[UnitTypeId.BROODLORD] += 12
                        composition[UnitTypeId.CORRUPTOR] += 3
                    if 0 < lair_count:
                        composition[UnitTypeId.HYDRALISK] += 12
                    else:
                        composition[UnitTypeId.ROACH] += 12

        return {k: int(math.floor(v)) for k, v in composition.items() if 0 < v}

    def filter_upgrade(self, upgrade) -> bool:
        if upgrade == UpgradeId.ZERGLINGMOVEMENTSPEED:
            return True
        elif not self._tech_up:
            return False
        elif upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL1:
            return 0 < self.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL1, include_planned=False)
        elif upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL2:
            return 0 < self.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL2, include_planned=False)
        elif upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL3:
            return 0 < self.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL3, include_planned=False)
        elif upgrade in ZERG_FLYER_UPGRADES or upgrade in ZERG_FLYER_ARMOR_UPGRADES:
            return 0 < self.count(UnitTypeId.GREATERSPIRE, include_planned=False)
        elif upgrade == UpgradeId.OVERLORDSPEED:
            return 8 * 60 < self.time
        else:
            return True
