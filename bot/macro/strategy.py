import enum
from collections import defaultdict
from dataclasses import dataclass
from functools import cached_property, total_ordering
from typing import Iterable

import numpy as np
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from bot.common.constants import (
    REQUIREMENTS,
    UNIT_COUNTER_DICT,
    WITH_TECH_EQUIVALENTS,
    ZERG_FLYER_ARMOR_UPGRADES,
    ZERG_FLYER_UPGRADES,
)
from bot.common.unit_composition import UnitComposition
from bot.macro.state import MacroId, MacroPlan
from bot.observation import Observation


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
    obs: Observation

    @cached_property
    def composition_deficit(self) -> UnitComposition:
        return self.composition_target - self.composition

    @cached_property
    def composition(self) -> UnitComposition:
        return UnitComposition.of(self.obs.bot.all_own_units)

    @cached_property
    def composition_target(self) -> UnitComposition:
        return self.macro_composition + self.army_composition

    @cached_property
    def enemy_composition(self) -> UnitComposition:
        return UnitComposition.of(self.obs.bot.all_enemy_units)

    def filter_upgrade(self, upgrade: UpgradeId) -> bool:
        if upgrade == UpgradeId.ZERGLINGMOVEMENTSPEED:
            return True
        elif self.tier == StrategyTier.Zero:
            return False
        elif upgrade == UpgradeId.BURROW:
            return self.tier >= StrategyTier.Hatch
        elif upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL1:
            return 0 < self.obs.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL1, include_planned=False)
        elif upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL2:
            return 0 < self.obs.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL2, include_planned=False)
        elif upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL3:
            return 0 < self.obs.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL3, include_planned=False)
        elif upgrade in ZERG_FLYER_UPGRADES or upgrade in ZERG_FLYER_ARMOR_UPGRADES:
            return 0 < self.obs.count(UnitTypeId.GREATERSPIRE, include_planned=False)
        elif upgrade == UpgradeId.OVERLORDSPEED:
            return self.tier >= StrategyTier.Lair
        else:
            return True

    def can_build(self, t: UnitTypeId) -> bool:
        return not any(self.obs.get_missing_requirements(t))

    @cached_property
    def army_composition(self) -> UnitComposition:
        if self.obs.bot.tech_requirement_progress(UnitTypeId.ZERGLING) < 0.8:
            return UnitComposition({})
        ratio = 2.0
        composition = self.counter_composition
        composition += {
            UnitTypeId.RAVAGER: composition[UnitTypeId.ROACH] / 13,
            UnitTypeId.CORRUPTOR: composition[UnitTypeId.BROODLORD] / 8,
        }
        composition = UnitComposition({k: v for k, v in composition.items() if 0 < v})
        if sum(composition.values()) < 1:
            composition += {UnitTypeId.ZERGLING: 1}
        banking = max(0, min(self.obs.bot.minerals, self.obs.bot.vespene) - 1000)
        if sum(composition.values()) < banking / 100:
            composition += {UnitTypeId.HYDRALISK: banking / 100}
            composition += {UnitTypeId.BROODLORD: banking / 100}
        return composition * ratio

    @cached_property
    def counter_composition(self) -> UnitComposition:
        def total_cost(t: UnitTypeId) -> float:
            return self.obs.bot.cost.of(t).total_resources

        composition = defaultdict[UnitTypeId, float](float)
        for enemy_type, count in self.enemy_composition.items():
            for counter in UNIT_COUNTER_DICT.get(enemy_type, []):
                if self.can_build(counter):
                    composition[counter] += count * total_cost(enemy_type) / total_cost(counter)
                    break
        return UnitComposition(composition)

    @cached_property
    def tier(self) -> StrategyTier:
        if self.obs.bot.supply_workers < 32 or self.obs.bot.townhalls.amount < 2:
            return StrategyTier.Zero
        elif self.obs.bot.supply_workers < 66 or self.obs.bot.townhalls.amount < 3:
            return StrategyTier.Hatch
        elif self.obs.bot.supply_workers < 80 or self.obs.bot.townhalls.amount < 4:
            return StrategyTier.Lair
        return StrategyTier.Hive

    @cached_property
    def force_global(self) -> float:
        return self.obs.bot.cost.of_composition(self.composition).total_resources

    @cached_property
    def enemy_force_global(self) -> float:
        return self.obs.bot.cost.of_composition(self.enemy_composition).total_resources

    @cached_property
    def confidence_global(self) -> float:
        return np.log1p(self.force_global) - np.log1p(self.enemy_force_global)

    @cached_property
    def macro_composition(self) -> UnitComposition:
        harvester_target = max(1, min(80, self.obs.max_harvesters))
        queen_target = max(0, min(12, (1 + self.obs.bot.townhalls.amount)))
        composition = UnitComposition(
            {
                UnitTypeId.DRONE: harvester_target,
                UnitTypeId.QUEEN: queen_target,
            }
        )
        burrowed_enemies = self.obs.enemy_units.filter(lambda u: u.is_burrowed)
        composition += {UnitTypeId.OVERSEER: max(10, len(burrowed_enemies))}
        if self.tier >= StrategyTier.Zero:
            pass
        if self.tier >= StrategyTier.Hatch:
            composition += {UnitTypeId.ROACHWARREN: 1}
            composition += {UnitTypeId.OVERSEER: 2}
        if self.tier >= StrategyTier.Lair:
            composition += {UnitTypeId.OVERSEER: 2}
            composition += {UnitTypeId.HYDRALISKDEN: 1}
            composition += {UnitTypeId.EVOLUTIONCHAMBER: 1}
        if self.tier >= StrategyTier.Hive:
            composition += {UnitTypeId.OVERSEER: 4}
            composition += {UnitTypeId.EVOLUTIONCHAMBER: 1}
            composition += {UnitTypeId.GREATERSPIRE: 1}
            if self.obs.count(UnitTypeId.GREATERSPIRE, include_planned=False) == 0:
                composition += {UnitTypeId.GREATERSPIRE: 1}
            else:
                composition += {UnitTypeId.SPIRE: 1}
        return composition

    def make_tech(self) -> Iterable[MacroPlan]:
        upgrades = [
            u
            for unit, count in self.composition_target.items()
            for u in self.obs.upgrades_by_unit(unit)
            if self.filter_upgrade(u)
        ]
        upgrades.append(UpgradeId.ZERGLINGMOVEMENTSPEED)
        targets: set[MacroId] = set(upgrades)
        targets.update(self.composition_target.keys())
        targets.update(r for item in set(targets) for r in REQUIREMENTS[item])
        for target in targets:
            if equivalents := WITH_TECH_EQUIVALENTS.get(target):
                target_met = any(self.obs.count(t) for t in equivalents)
            else:
                target_met = bool(self.obs.count(target))
            if not target_met:
                yield MacroPlan(target, priority=-0.5)

    def expand(self) -> Iterable[MacroPlan]:

        if self.obs.bot.time < 50:
            return
        if 2 == self.obs.bot.townhalls.amount and 2 > self.obs.count(UnitTypeId.QUEEN, include_planned=False):
            return

        worker_max = self.obs.max_harvesters
        saturation = max(0, min(1, self.obs.bot.state.score.food_used_economy / max(1, worker_max)))
        if 2 < self.obs.bot.townhalls.amount and 4 / 5 > saturation:
            return

        priority = 5 * (saturation - 1)
        # TODO: prioritize everything on the fly
        # for plan in self.macro.planned_by_type(UnitTypeId.HATCHERY):
        #     if plan.priority < math.inf:
        #         plan.priority = priority

        if 0 < self.obs.count(UnitTypeId.HATCHERY, include_actual=False):
            return
        yield MacroPlan(UnitTypeId.HATCHERY, priority=priority, max_distance=None)

    def morph_overlord(self) -> Iterable[MacroPlan]:
        supply = self.obs.bot.supply_cap + self.obs.supply_pending / 2 + self.obs.supply_planned
        supply_target = min(200.0, self.obs.bot.supply_used + 2 + 20 * self.obs.income.larva)
        if supply_target <= supply:
            return
        yield MacroPlan(UnitTypeId.OVERLORD, priority=1)
