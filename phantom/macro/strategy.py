import enum
from collections import defaultdict
from collections.abc import Iterable
from functools import total_ordering
from typing import TYPE_CHECKING

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
from phantom.macro.main import MacroPlan
from phantom.parameter_sampler import ParameterSampler, Prior

if TYPE_CHECKING:
    from phantom.main import PhantomBot


@total_ordering
class StrategyTier(enum.IntEnum):
    HATCH = 0
    LAIR = 1
    HIVE = 2
    LATEGAME = 3


class StrategyParameters:
    def __init__(self, parameters: ParameterSampler) -> None:
        self.counter_factor = parameters.add(Prior(2.5, 0.1, min=0))
        self.ravager_mixin = parameters.add(Prior(8, 1, min=0))
        self.corruptor_mixin = parameters.add(Prior(8, 1, min=0))
        self.tier1_drone_count = parameters.add(Prior(32, 1, min=0))
        self.tier2_drone_count = parameters.add(Prior(66, 1, min=0))
        self.tier3_drone_count = parameters.add(Prior(80, 1, min=0))
        self.tech_priority_offset = parameters.add(Prior(-1.0, 0.01))
        self.tech_priority_scale = parameters.add(Prior(0.5, 0.01, min=0))
        self.hydras_when_banking = parameters.add(Prior(5, 1, min=0))
        self.lings_when_banking = parameters.add(Prior(10, 1, min=0))
        self.queens_when_banking = parameters.add(Prior(3, 1, min=0))


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

    def make_upgrades(self) -> Iterable[MacroPlan]:
        upgrade_weights = dict[UpgradeId, float]()
        for unit, count in self.composition_target.items():
            cost = self.bot.cost.of(unit)
            total_cost = cost.minerals + 2 * cost.vespene
            for upgrade in self.bot.upgrades_by_unit(unit):
                upgrade_weights[upgrade] = upgrade_weights.setdefault(upgrade, 0.0) + count / total_cost

        # strategy specific filter
        upgrade_weights = {k: v for k, v in upgrade_weights.items() if self.filter_upgrade(k)}

        if not upgrade_weights:
            return
        total = max(upgrade_weights.values())
        if total == 0:
            return

        upgrade_priorities = {
            k: self.parameters.tech_priority_offset.value + self.parameters.tech_priority_scale.value * v / total
            for k, v in upgrade_weights.items()
        }

        for plan in self.bot.agent.macro.unassigned_plans:
            if priority := upgrade_priorities.get(plan.item):
                plan.priority = priority

        for plan in self.bot.agent.macro.assigned_plans.values():
            if priority := upgrade_priorities.get(plan.item):
                plan.priority = priority

        for upgrade, priority in upgrade_priorities.items():
            if (
                upgrade in self.bot.state.upgrades
                or upgrade in self.bot.pending_upgrades.values()
                or self.bot.count_planned(upgrade)
            ):
                continue
            yield MacroPlan(upgrade, priority=priority)

    def expand(self) -> Iterable[MacroPlan]:
        worker_max = self.bot.max_harvesters + 22 * self.bot.count_pending(UnitTypeId.HATCHERY)
        saturation = self.bot.supply_workers / max(1, worker_max)
        saturation = max(0.0, min(1.0, saturation))

        # if self.tier == StrategyTier.HATCH:
        #     return

        priority = 3 * (saturation - 1)

        for plan in self.bot.agent.macro.assigned_plans.values():
            if plan.item == UnitTypeId.HATCHERY:
                plan.priority = priority

        if priority < -1:
            return
        if self.bot.count_planned(UnitTypeId.HATCHERY) > 0:
            return
        if self.bot.ordered_by_type[UnitTypeId.HATCHERY] > 0:
            return

        yield MacroPlan(UnitTypeId.HATCHERY, priority=priority)

    def make_spines(self) -> Iterable[MacroPlan]:
        if not self.bot.mediator.get_did_enemy_rush:
            return

        if self.bot.time > 300:
            return

        for base in self.bot.bases_taken:
            if base == self.bot.start_location_rounded:
                continue
            spine_position = self.bot.spine_position[base]
            if spine_position in self.bot.structure_dict:
                continue
            if not self.bot.mediator.can_place_structure(
                position=spine_position,
                structure_type=UnitTypeId.SPINECRAWLER,
                include_addon=False,
            ):
                continue
            yield MacroPlan(UnitTypeId.SPINECRAWLER, target=Point2(spine_position))

    def make_spores(self) -> Iterable[MacroPlan]:
        if self.bot.actual_iteration % 31 != 0:
            return

        timing = SPORE_TIMINGS[self.bot.enemy_race]
        if self.bot.time < timing:
            return

        triggers = SPORE_TRIGGERS[self.bot.enemy_race]
        if not self.bot.enemy_units(triggers).exists:
            return

        for base in self.bot.bases_taken:
            spore_position = self.bot.spore_position[base]
            if spore_position in self.bot.structure_dict:
                continue
            if not self.bot.mediator.can_place_structure(
                position=spore_position,
                structure_type=UnitTypeId.SPORECRAWLER,
                include_addon=False,
            ):
                continue
            yield MacroPlan(UnitTypeId.SPORECRAWLER, target=Point2(spore_position))

    def morph_overlord(self) -> Iterable[MacroPlan]:
        supply_planned = sum(
            provided * (self.bot.count_planned(unit_type) + self.bot.count_pending(unit_type))
            for unit_type, provided in SUPPLY_PROVIDED[self.bot.race].items()
        )
        supply = self.bot.supply_cap + supply_planned
        supply_target = min(200.0, self.bot.supply_used + 2 + 20 * self.bot.income.larva)
        if supply_target <= supply:
            return
        yield MacroPlan(UnitTypeId.OVERLORD, priority=1)

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
            return self.tier >= StrategyTier.HIVE
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
        # elif upgrade in {UpgradeId.ZERGMISSILEWEAPONSLEVEL1, UpgradeId.ZERGMELEEWEAPONSLEVEL1}:
        #     return UpgradeId.ZERGGROUNDARMORSLEVEL1 in upgrade_set
        # elif upgrade in {UpgradeId.ZERGMISSILEWEAPONSLEVEL2, UpgradeId.ZERGMELEEWEAPONSLEVEL2}:
        #     return UpgradeId.ZERGGROUNDARMORSLEVEL2 in upgrade_set
        # elif upgrade in {UpgradeId.ZERGMISSILEWEAPONSLEVEL3, UpgradeId.ZERGMELEEWEAPONSLEVEL3}:
        #     return UpgradeId.ZERGGROUNDARMORSLEVEL3 in upgrade_set
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
        # vision = PlayerVision.from_units(self.bot.units | self.bot.enemy_units)
        # enemy_vision = SCOUT_PREDICTOR.predict(self.bot.game_loop, vision, self.bot.player_races)
        # composition = UnitComposition(dict(enemy_vision.composition)) + self.enemy_composition
        # composition = UnitComposition({k: v for k, v in composition.items() if v >= 1})
        # return composition

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
        # force droning up to 21
        # TODO: check if necessary
        if not self.bot.structures({UnitTypeId.SPAWNINGPOOL}).ready:
            return {}
        counter_composition = {k: self.parameters.counter_factor.value * v for k, v in self.counter_composition.items()}
        composition = defaultdict[UnitTypeId, float](float, counter_composition)
        corruptor_mixin = int(composition[UnitTypeId.BROODLORD] / self.parameters.corruptor_mixin.value)
        if corruptor_mixin > 0:
            composition[UnitTypeId.CORRUPTOR] += corruptor_mixin
        ravager_mixin = int(composition[UnitTypeId.ROACH] / self.parameters.ravager_mixin.value)
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
        if self.parameters.hydras_when_banking.value < can_afford_hydras:
            composition[UnitTypeId.HYDRALISK] += can_afford_hydras
            composition[UnitTypeId.BROODLORD] += can_afford_hydras
        else:
            if self.parameters.lings_when_banking.value < can_afford_lings:
                composition[UnitTypeId.ZERGLING] += can_afford_lings
            if self.parameters.queens_when_banking.value < can_afford_queens:
                composition[UnitTypeId.QUEEN] += can_afford_queens
        return composition

    def _counter_composition(self) -> UnitComposition:
        def total_cost(t: UnitTypeId) -> float:
            return float(self.bot.cost.of(t).total_resources)

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
        harvester_target = min(100, max(1, self.bot.max_harvesters))
        queen_target = max(0.0, min(8, 2 * self.bot.townhalls.amount))
        composition = defaultdict[UnitTypeId, float](float)

        composition[UnitTypeId.DRONE] += harvester_target
        composition[UnitTypeId.QUEEN] += queen_target
        if self.tier >= StrategyTier.HATCH:
            composition[UnitTypeId.SPAWNINGPOOL] += 1
        if self.tier >= StrategyTier.LAIR:
            composition[UnitTypeId.LAIR] += 1
            composition[UnitTypeId.OVERSEER] += 2
            composition[UnitTypeId.ROACHWARREN] += 1
            composition[UnitTypeId.HYDRALISKDEN] += 1
            composition[UnitTypeId.EVOLUTIONCHAMBER] += 1
        if self.tier >= StrategyTier.HIVE:
            composition[UnitTypeId.INFESTATIONPIT] += 1
            composition[UnitTypeId.HIVE] += 1
            composition[UnitTypeId.OVERSEER] += 3
            composition[UnitTypeId.EVOLUTIONCHAMBER] += 1
        if self.tier >= StrategyTier.LATEGAME:
            composition[UnitTypeId.OVERSEER] += 4
            composition[UnitTypeId.SPIRE] += 1
            composition[UnitTypeId.GREATERSPIRE] += 1
        return composition
