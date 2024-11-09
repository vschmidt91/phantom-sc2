import math
from dataclasses import dataclass
from typing import Counter, TypeAlias

import numpy as np
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from .base import BotBase
from .constants import UNIT_COUNTER_DICT, ZERG_FLYER_ARMOR_UPGRADES, ZERG_FLYER_UPGRADES

Composition: TypeAlias = dict[UnitTypeId, int]


@dataclass(frozen=True)
class Strategy:
    context: BotBase
    composition: Composition
    tech_up: bool

    def filter_upgrade(self, upgrade: UpgradeId) -> bool:
        if upgrade == UpgradeId.ZERGLINGMOVEMENTSPEED:
            return True
        elif not self.tech_up:
            return False
        elif upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL1:
            return 0 < self.context.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL1, include_planned=False)
        elif upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL2:
            return 0 < self.context.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL2, include_planned=False)
        elif upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL3:
            return 0 < self.context.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL3, include_planned=False)
        elif upgrade in ZERG_FLYER_UPGRADES or upgrade in ZERG_FLYER_ARMOR_UPGRADES:
            return 0 < self.context.count(UnitTypeId.GREATERSPIRE, include_planned=False)
        elif upgrade == UpgradeId.OVERLORDSPEED:
            return 8 * 60 < self.context.time
        else:
            return True


def decide_strategy(context: BotBase, worker_target: int, confidence: float) -> Strategy:

    worker_count = context.state.score.food_used_economy

    ratio = max(
        1 - confidence,
        worker_count / worker_target,
    )
    queen_target = 1 + context.townhalls.amount
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

    can_build = {t: not any(context.get_missing_requirements(t)) for t in composition}

    enemy_counts = Counter[UnitTypeId](
        enemy.type_id for enemy in context.all_enemy_units if enemy.type_id in UNIT_COUNTER_DICT
    )

    tech_up = 32 <= worker_count and 3 <= context.townhalls.amount
    lair_count = context.count(UnitTypeId.LAIR, include_pending=False, include_planned=False)
    hive_count = context.count(UnitTypeId.HIVE, include_pending=True, include_planned=False)

    def total_cost(t: UnitTypeId) -> float:
        c = context.cost.of(t)
        return c.minerals + c.vespene

    if any(enemy_counts):
        for enemy_type, count in enemy_counts.items():
            for counter in UNIT_COUNTER_DICT.get(enemy_type, []):
                if can_build[counter]:
                    composition[counter] += 2.5 * ratio * count * total_cost(enemy_type) / total_cost(counter)
                    break
    elif 0.8 < context.tech_requirement_progress(UnitTypeId.ZERGLING):
        composition[UnitTypeId.ZERGLING] = 1.0

    composition[UnitTypeId.RAVAGER] += composition[UnitTypeId.ROACH] / 13
    composition[UnitTypeId.CORRUPTOR] += composition[UnitTypeId.BROODLORD] / 8

    if tech_up:
        composition[UnitTypeId.ROACHWARREN] = 1
        composition[UnitTypeId.OVERSEER] = 1

    if tech_up and 0 < lair_count + hive_count and 150 < context.supply_used:
        composition[UnitTypeId.HYDRALISKDEN] = 1
        composition[UnitTypeId.OVERSEER] = 2
        composition[UnitTypeId.EVOLUTIONCHAMBER] = 2

    if tech_up and 0 < hive_count and 150 < context.supply_used:
        if 0 == context.count(UnitTypeId.SPIRE, include_planned=False) + context.count(
            UnitTypeId.SPIRE, include_planned=False
        ):
            composition[UnitTypeId.SPIRE] = 1
        else:
            composition[UnitTypeId.GREATERSPIRE] = 1
        composition[UnitTypeId.OVERSEER] = 3

    if worker_count == worker_target:
        banking_minerals = max(0, context.minerals - 300)
        banking_gas = max(0, context.minerals - 300)
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

    composition = {k: int(math.floor(v)) for k, v in composition.items() if 0 < v}

    return Strategy(context, composition, tech_up)
