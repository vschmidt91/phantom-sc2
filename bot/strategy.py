import enum
import math
from dataclasses import dataclass
from typing import Counter, TypeAlias

import numpy as np
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from bot.base import BotBase
from bot.constants import (
    UNIT_COUNTER_DICT,
    ZERG_FLYER_ARMOR_UPGRADES,
    ZERG_FLYER_UPGRADES,
)

Composition: TypeAlias = dict[UnitTypeId, int]


class StrategyTier(enum.Enum):
    Zero = enum.auto()
    Hatch = enum.auto()
    Lair = enum.auto()
    Hive = enum.auto()


@dataclass(frozen=True)
class Strategy:
    context: BotBase
    composition: Composition
    tech_up: StrategyTier

    def filter_upgrade(self, upgrade: UpgradeId) -> bool:
        if upgrade == UpgradeId.ZERGLINGMOVEMENTSPEED:
            return True
        elif self.tech_up == StrategyTier.Zero:
            return False
        elif upgrade == UpgradeId.BURROW:
            return self.tech_up != StrategyTier.Hatch
        elif upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL1:
            return 0 < self.context.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL1, include_planned=False)
        elif upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL2:
            return 0 < self.context.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL2, include_planned=False)
        elif upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL3:
            return 0 < self.context.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL3, include_planned=False)
        elif upgrade in ZERG_FLYER_UPGRADES or upgrade in ZERG_FLYER_ARMOR_UPGRADES:
            return 0 < self.context.count(UnitTypeId.GREATERSPIRE, include_planned=False)
        elif upgrade == UpgradeId.OVERLORDSPEED:
            return self.tech_up == StrategyTier.Hive
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

    tier = StrategyTier.Hive
    if worker_count < 32 or context.townhalls.amount < 3:
        tier = StrategyTier.Zero
    elif worker_count < 66 or context.townhalls.amount < 4:
        tier = StrategyTier.Hatch
    elif worker_count < 80 or context.townhalls.amount < 5:
        tier = StrategyTier.Lair

    if tier == StrategyTier.Zero:
        pass
    elif tier == StrategyTier.Hatch:
        composition[UnitTypeId.ROACHWARREN] = 1
        composition[UnitTypeId.OVERSEER] = 1
    elif tier == StrategyTier.Lair:
        composition[UnitTypeId.OVERSEER] = 3
        composition[UnitTypeId.HYDRALISKDEN] = 1
        composition[UnitTypeId.EVOLUTIONCHAMBER] = 1
    elif tier == StrategyTier.Hive:
        composition[UnitTypeId.EVOLUTIONCHAMBER] = 2
        composition[UnitTypeId.OVERSEER] = 5
        if 0 == context.count(UnitTypeId.SPIRE, include_planned=False):
            composition[UnitTypeId.SPIRE] = 1
        else:
            composition[UnitTypeId.GREATERSPIRE] = 1

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

    return Strategy(context, composition, tier)
