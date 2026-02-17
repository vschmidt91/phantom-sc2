import enum
from collections import defaultdict
from collections.abc import Mapping
from functools import cached_property, total_ordering
from typing import TYPE_CHECKING

import numpy as np
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2

from phantom.common.constants import (
    SPORE_TIMINGS,
    SPORE_TRIGGERS,
    SUPPLY_PROVIDED,
    UNIT_COUNTER_DICT,
    ZERG_FLYER_ARMOR_UPGRADES,
    ZERG_FLYER_UPGRADES,
)
from phantom.common.unit_composition import UnitComposition, add_compositions, composition_of, sub_compositions
from phantom.common.utils import MacroId
from phantom.learn.parameters import OptimizationTarget, ParameterManager, Prior
from phantom.macro.builder import MacroPlan

if TYPE_CHECKING:
    from phantom.main import PhantomBot


@total_ordering
class StrategyTier(enum.IntEnum):
    HATCH = 0
    LAIR = 1
    HIVE = 2
    LATEGAME = 3


class StrategyParameters:
    def __init__(self, params: ParameterManager) -> None:
        self.ravager_mixin = 10
        self.corruptor_mixin = 5
        self.tier1_drone_count = params.optimize[OptimizationTarget.CostEfficiency].add(
            "tier1_drone_count", Prior(30, 1)
        )
        self.tier2_drone_count = params.optimize[OptimizationTarget.CostEfficiency].add(
            "tier2_drone_count", Prior(60, 1)
        )
        self.tier3_drone_count = params.optimize[OptimizationTarget.CostEfficiency].add(
            "tier3_drone_count", Prior(100, 1)
        )
        self.hydras_when_banking = 13
        self.lings_when_banking = 8
        self.queens_when_banking = 4
        self.supply_buffer_log = params.optimize[OptimizationTarget.SupplyEfficiency].add(
            "supply_buffer_log", Prior(2.0, 0.3)
        )

    @property
    def supply_buffer(self) -> float:
        return np.exp(self.supply_buffer_log.value)


class Strategy:
    def __init__(self, bot: "PhantomBot", parameters: StrategyParameters) -> None:
        self.bot = bot
        self.parameters = parameters
        self.composition = composition_of(bot.all_own_units)
        self.enemy_composition = composition_of(bot.all_enemy_units)
        self.enemy_composition_predicted = self._predict_enemy_composition()
        self.counter_composition = self._counter_composition()
        self.army_composition = self._army_composition()
        self.tier = self._tier()
        self.macro_composition = self._macro_composition()
        self.composition_target = add_compositions(self.macro_composition, self.army_composition)
        self.composition_deficit = sub_compositions(self.composition_target, self.composition)

    def make_spines(self) -> Mapping[UnitTypeId, MacroPlan]:
        if not self.bot.mediator.get_did_enemy_rush:
            return {}

        if self.bot.time > 300:
            return {}

        for expansion in self.bot.bases_taken.values():
            if expansion.spine_position not in self.bot.structure_dict and self.bot.mediator.can_place_structure(
                position=expansion.spine_position, structure_type=UnitTypeId.SPINECRAWLER
            ):
                return {
                    UnitTypeId.SPINECRAWLER: MacroPlan(
                        target=Point2(expansion.spine_position), allow_replacement=False, priority=1.0
                    )
                }
        return {}

    def make_spores(self) -> Mapping[UnitTypeId, MacroPlan]:
        if self.bot.actual_iteration % 31 != 0:
            return {}

        timing = SPORE_TIMINGS[self.bot.enemy_race]
        if self.bot.time < timing:
            return {}

        triggers = SPORE_TRIGGERS[self.bot.enemy_race]
        if not self.bot.enemy_units(triggers).exists:
            return {}

        for expansion in self.bot.bases_taken.values():
            if expansion.spore_position not in self.bot.structure_dict and self.bot.mediator.can_place_structure(
                position=expansion.spore_position, structure_type=UnitTypeId.SPORECRAWLER
            ):
                return {
                    UnitTypeId.SPORECRAWLER: MacroPlan(
                        target=Point2(expansion.spore_position), allow_replacement=False, priority=1.0
                    )
                }

        return {}

    def morph_overlord(self) -> Mapping[MacroId, float]:
        supply_planned = sum(
            provided * (self.bot.count_planned(unit_type) + self.bot.count_pending(unit_type))
            for unit_type, provided in SUPPLY_PROVIDED[self.bot.race].items()
        )
        supply = self.bot.supply_cap + supply_planned
        supply_buffer = max(2, self.parameters.supply_buffer * self.bot.income.larva)
        supply_target = min(200.0, self.bot.supply_used + supply_buffer)
        if supply_target <= supply:
            return {}
        return {UnitTypeId.OVERLORD: 3.0}

    def can_build(self, t: UnitTypeId) -> bool:
        return not any(self.bot.get_missing_requirements(t))

    def filter_upgrade(self, upgrade: UpgradeId) -> bool:
        def upgrade_researched_or_pending(u: UpgradeId) -> bool:
            return self.bot.count_actual(u) + self.bot.count_pending(u) > 0

        if upgrade == UpgradeId.ZERGLINGMOVEMENTSPEED:
            return True
        elif self.tier == StrategyTier.HATCH:
            return False
        elif upgrade == UpgradeId.BURROW:
            return upgrade_researched_or_pending(UpgradeId.GLIALRECONSTITUTION)
        elif upgrade == UpgradeId.ZERGLINGATTACKSPEED:
            return True
        elif upgrade == UpgradeId.TUNNELINGCLAWS:
            return upgrade_researched_or_pending(UpgradeId.GLIALRECONSTITUTION)
        elif upgrade == UpgradeId.EVOLVEGROOVEDSPINES:
            return upgrade_researched_or_pending(UpgradeId.EVOLVEMUSCULARAUGMENTS)
        elif upgrade in {
            UpgradeId.ZERGMELEEWEAPONSLEVEL1,
            UpgradeId.ZERGMISSILEWEAPONSLEVEL1,
        }:
            return self.bot.count_actual(UnitTypeId.ROACHWARREN) > 0
        elif upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL1:
            return upgrade_researched_or_pending(UpgradeId.ZERGMISSILEWEAPONSLEVEL1) or upgrade_researched_or_pending(
                UpgradeId.ZERGMELEEWEAPONSLEVEL1
            )
        elif upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL2:
            return upgrade_researched_or_pending(UpgradeId.ZERGMISSILEWEAPONSLEVEL2) or upgrade_researched_or_pending(
                UpgradeId.ZERGMELEEWEAPONSLEVEL2
            )
        elif upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL3:
            return upgrade_researched_or_pending(UpgradeId.ZERGMISSILEWEAPONSLEVEL3) or upgrade_researched_or_pending(
                UpgradeId.ZERGMELEEWEAPONSLEVEL3
            )
        elif upgrade in ZERG_FLYER_UPGRADES or upgrade in ZERG_FLYER_ARMOR_UPGRADES:
            return bool(self.bot.count_actual(UnitTypeId.GREATERSPIRE)) or bool(
                self.bot.count_pending(UnitTypeId.GREATERSPIRE)
            )
        elif upgrade == UpgradeId.OVERLORDSPEED:
            return self.tier >= StrategyTier.HIVE
        else:
            return True

    def _predict_enemy_composition(self) -> UnitComposition:
        return self.enemy_composition

    def _tier(self) -> StrategyTier:
        if (
            self.bot.supply_workers < self.parameters.tier1_drone_count.value
            or self.bot.townhalls.amount < 3
            or self.bot.time < 3 * 60
        ):
            return StrategyTier.HATCH
        elif (
            self.bot.supply_workers < self.parameters.tier2_drone_count.value
            or self.bot.townhalls.amount < 4
            or self.bot.time < 6 * 60
        ):
            return StrategyTier.LAIR
        elif (
            self.bot.supply_workers < self.parameters.tier3_drone_count.value
            or self.bot.townhalls.amount < 5
            or self.bot.time < 9 * 60
        ):
            return StrategyTier.HIVE
        return StrategyTier.LATEGAME

    def _army_composition(self) -> UnitComposition:
        # counter_composition = {k: self.parameters.counter_factor.value * v for k, v in self.counter_composition.items()}
        counter_composition = self.counter_composition
        composition = defaultdict[UnitTypeId, float](float, counter_composition)
        corruptor_mixin = int(composition[UnitTypeId.BROODLORD] / self.parameters.corruptor_mixin)
        if corruptor_mixin > 0:
            composition[UnitTypeId.CORRUPTOR] += corruptor_mixin
        ravager_mixin = int(composition[UnitTypeId.ROACH] / self.parameters.ravager_mixin)
        if ravager_mixin > 0:
            composition[UnitTypeId.RAVAGER] += ravager_mixin
        if sum(composition.values()) < 1:
            composition[UnitTypeId.ZERGLING] += 2
        can_afford_hydras = min(
            self.bot.bank.minerals / 100,
            self.bot.bank.vespene / 50,
            self.bot.bank.larva,
        )
        can_afford_lings = min(
            self.bot.bank.minerals / 50,
            self.bot.bank.larva,
        )
        can_afford_queens = self.bot.bank.minerals / 150
        if self.parameters.hydras_when_banking < can_afford_hydras:
            composition[UnitTypeId.HYDRALISK] += can_afford_hydras
            composition[UnitTypeId.BROODLORD] += can_afford_hydras
        else:
            if self.parameters.lings_when_banking < can_afford_lings:
                composition[UnitTypeId.ZERGLING] += can_afford_lings
            if self.parameters.queens_when_banking < can_afford_queens:
                composition[UnitTypeId.QUEEN] += can_afford_queens
        return composition

    def _counter_composition(self) -> UnitComposition:
        def total_cost(t: UnitTypeId) -> float:
            cost = self.bot.cost.of(t)
            total_cost = (cost.minerals + 2 * cost.vespene) * (0.5 if t == UnitTypeId.ZERGLING else 1.0)
            return total_cost

        composition = defaultdict[UnitTypeId, float](float)
        for enemy_type, count in self.enemy_composition_predicted.items():
            enemy_cost = total_cost(enemy_type)
            if counters := UNIT_COUNTER_DICT.get(enemy_type):
                buildable_counters = {k: v for k, v in counters.items() if self.can_build(k)}
                if any(buildable_counters):
                    sum_weights = sum(buildable_counters.values())
                    for counter, weight in buildable_counters.items():
                        composition[counter] += count * enemy_cost * weight / (total_cost(counter) * sum_weights)
        return composition

    def _macro_composition(self) -> UnitComposition:
        harvester_target = min(self.parameters.tier3_drone_count.value, max(1, self.bot.max_harvesters))
        queen_target = max(0.0, min(8, 2 * self.bot.townhalls.amount))
        composition = defaultdict[UnitTypeId, float](float)

        composition[UnitTypeId.DRONE] += harvester_target
        composition[UnitTypeId.QUEEN] += queen_target
        if self.tier >= StrategyTier.HATCH:
            composition[UnitTypeId.SPAWNINGPOOL] += 1
        if self.tier >= StrategyTier.LAIR:
            if UnitTypeId.HIVE not in self.composition:
                composition[UnitTypeId.LAIR] += 1
            composition[UnitTypeId.OVERSEER] += 1
        if self.tier >= StrategyTier.HIVE:
            composition[UnitTypeId.HIVE] += 1
            composition[UnitTypeId.OVERSEER] += 1
        if self.tier >= StrategyTier.LATEGAME:
            composition[UnitTypeId.OVERSEER] += 1
            composition[UnitTypeId.GREATERSPIRE] += 1
        return composition

    @cached_property
    def tech_composition(self) -> UnitComposition:
        composition = defaultdict[UnitTypeId, float](float)
        if self.tier >= StrategyTier.HATCH:
            composition[UnitTypeId.SPAWNINGPOOL] += 1
            composition[UnitTypeId.ROACHWARREN] += 1
        if self.tier >= StrategyTier.LAIR:
            composition[UnitTypeId.HYDRALISKDEN] += 1
            composition[UnitTypeId.EVOLUTIONCHAMBER] += 1
        if self.tier >= StrategyTier.HIVE:
            composition[UnitTypeId.INFESTATIONPIT] += 1
            composition[UnitTypeId.EVOLUTIONCHAMBER] += 1
        if self.tier >= StrategyTier.LATEGAME and UnitTypeId.GREATERSPIRE not in self.composition:
            composition[UnitTypeId.SPIRE] += 1
        return composition
