import enum
from collections import defaultdict
from dataclasses import dataclass
from functools import cached_property, total_ordering

import numpy as np
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from bot.common.constants import (
    UNIT_COUNTER_DICT,
    ZERG_FLYER_ARMOR_UPGRADES,
    ZERG_FLYER_UPGRADES,
)
from bot.common.main import BotBase
from bot.common.unit_composition import UnitComposition


@total_ordering
class StrategyTier(enum.Enum):
    Zero = 0
    Hatch = 1
    Lair = 2
    Hive = 3

    def __ge__(self, other):
        return self.value >= other.value


@dataclass(frozen=True)
class Strategy:
    context: BotBase
    max_harvesters: int

    @cached_property
    def composition_deficit(self) -> UnitComposition:
        return self.composition_target - self.composition

    @cached_property
    def composition(self) -> UnitComposition:
        return UnitComposition.of(self.context.all_own_units)

    @cached_property
    def composition_target(self) -> UnitComposition:
        return self.macro_composition + self.army_composition

    @cached_property
    def enemy_composition(self) -> UnitComposition:
        return UnitComposition.of(self.context.all_enemy_units)

    def filter_upgrade(self, upgrade: UpgradeId) -> bool:
        if upgrade == UpgradeId.ZERGLINGMOVEMENTSPEED:
            return True
        elif self.tier == StrategyTier.Zero:
            return False
        elif upgrade == UpgradeId.BURROW:
            return self.tier >= StrategyTier.Hatch
        elif upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL1:
            return 0 < self.context.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL1, include_planned=False)
        elif upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL2:
            return 0 < self.context.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL2, include_planned=False)
        elif upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL3:
            return 0 < self.context.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL3, include_planned=False)
        elif upgrade in ZERG_FLYER_UPGRADES or upgrade in ZERG_FLYER_ARMOR_UPGRADES:
            return 0 < self.context.count(UnitTypeId.GREATERSPIRE, include_planned=False)
        elif upgrade == UpgradeId.OVERLORDSPEED:
            return self.tier >= StrategyTier.Lair
        else:
            return True

    def can_build(self, t: UnitTypeId) -> bool:
        return not any(self.context.get_missing_requirements(t))

    @cached_property
    def army_composition(self) -> UnitComposition:
        if self.context.tech_requirement_progress(UnitTypeId.ZERGLING) < 0.8:
            return UnitComposition({})
        saturation = self.context.state.score.food_used_economy / self.max_harvesters
        ratio = 2.5 * max(1 - self.confidence_global, saturation)
        ratio = 2.0
        composition = self.counter_composition
        composition += {
            UnitTypeId.RAVAGER: composition[UnitTypeId.ROACH] / 13,
            UnitTypeId.CORRUPTOR: composition[UnitTypeId.BROODLORD] / 8,
        }
        composition = UnitComposition({k: v for k, v in composition.items() if 0 < v})
        if sum(composition.values()) < 1:
            composition += {UnitTypeId.ZERGLING: 1}
        return composition * ratio

    @cached_property
    def counter_composition(self) -> UnitComposition:
        def total_cost(t: UnitTypeId) -> float:
            return self.context.cost.of(t).total_resources

        composition = defaultdict[UnitTypeId, float](float)
        for enemy_type, count in self.enemy_composition.items():
            for counter in UNIT_COUNTER_DICT.get(enemy_type, []):
                if self.can_build(counter):
                    composition[counter] += count * total_cost(enemy_type) / total_cost(counter)
                    break
        return UnitComposition(composition)

    @cached_property
    def tier(self) -> StrategyTier:
        if self.context.supply_workers < 32 or self.context.townhalls.amount < 3:
            return StrategyTier.Zero
        elif self.context.supply_workers < 66 or self.context.townhalls.amount < 4:
            return StrategyTier.Hatch
        elif self.context.supply_workers < 80 or self.context.townhalls.amount < 5:
            return StrategyTier.Lair
        return StrategyTier.Hive

    @cached_property
    def force_global(self) -> float:
        return self.context.cost.of_composition(self.composition).total_resources

    @cached_property
    def enemy_force_global(self) -> float:
        return self.context.cost.of_composition(self.enemy_composition).total_resources

    @cached_property
    def confidence_global(self) -> float:
        return np.log1p(self.force_global) - np.log1p(self.enemy_force_global)

    @cached_property
    def macro_composition(self) -> UnitComposition:
        harvester_target = self.max_harvesters
        if 2 > self.context.townhalls.ready.amount:
            harvester_target = min(19, harvester_target)
        queen_target = max(0, min(12, (1 + self.context.townhalls.amount)))
        composition = UnitComposition(
            {
                UnitTypeId.DRONE: harvester_target,
                UnitTypeId.QUEEN: queen_target,
            }
        )
        if self.tier >= StrategyTier.Zero:
            pass
        if self.tier >= StrategyTier.Hatch:
            composition += {UnitTypeId.ROACHWARREN: 1}
            composition += {UnitTypeId.OVERSEER: 1}
        if self.tier >= StrategyTier.Lair:
            composition += {UnitTypeId.OVERSEER: 2}
            composition += {UnitTypeId.HYDRALISKDEN: 1}
            composition += {UnitTypeId.EVOLUTIONCHAMBER: 1}
        if self.tier >= StrategyTier.Hive:
            composition += {UnitTypeId.OVERSEER: 2}
            composition += {UnitTypeId.EVOLUTIONCHAMBER: 1}
            composition += {UnitTypeId.GREATERSPIRE: 1}
            if self.context.count(UnitTypeId.GREATERSPIRE, include_planned=False) == 0:
                composition += {UnitTypeId.GREATERSPIRE: 1}
            else:
                composition += {UnitTypeId.SPIRE: 1}
        return composition
