import enum
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cached_property, total_ordering

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from phantom.common.constants import (
    REQUIREMENTS,
    UNIT_COUNTER_DICT,
    WITH_TECH_EQUIVALENTS,
    ZERG_FLYER_ARMOR_UPGRADES,
    ZERG_FLYER_UPGRADES,
)
from phantom.common.unit_composition import UnitComposition
from phantom.data.normal import NormalParameter
from phantom.macro.state import MacroId, MacroPlan
from phantom.observation import Observation


@dataclass(frozen=True)
class StrategyParameters:
    counter_factor: NormalParameter
    ravager_mixin: NormalParameter
    corruptor_mixin: NormalParameter
    tier1_drone_count: NormalParameter
    tier2_drone_count: NormalParameter
    tier3_drone_count: NormalParameter
    tech_priority: NormalParameter
    hydras_when_banking: NormalParameter
    lings_when_banking: NormalParameter
    queens_when_banking: NormalParameter
    queens_per_hatch: NormalParameter
    queens_limit: NormalParameter


StrategyPrior = StrategyParameters(
    counter_factor=NormalParameter.prior(2, 0.1),
    ravager_mixin=NormalParameter.prior(21, 1),
    corruptor_mixin=NormalParameter.prior(13, 1),
    tier1_drone_count=NormalParameter.prior(32, 1),
    tier2_drone_count=NormalParameter.prior(66, 2),
    tier3_drone_count=NormalParameter.prior(80, 3),
    tech_priority=NormalParameter.prior(-0.25, 0.1),
    hydras_when_banking=NormalParameter.prior(10, 1),
    lings_when_banking=NormalParameter.prior(10, 1),
    queens_when_banking=NormalParameter.prior(3, 1),
    queens_per_hatch=NormalParameter.prior(1.5, 0.1),
    queens_limit=NormalParameter.prior(12, 1),
)


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
    param: StrategyParameters
    flood_lings: bool

    @cached_property
    def composition_deficit(self) -> UnitComposition:
        return self.composition_target - self.composition

    @cached_property
    def composition(self) -> UnitComposition:
        return UnitComposition.of(self.obs.units)

    @cached_property
    def composition_target(self) -> UnitComposition:
        return self.macro_composition + self.army_composition

    @cached_property
    def enemy_composition(self) -> UnitComposition:
        return UnitComposition.of(self.obs.enemy_units)

    def filter_upgrade(self, upgrade: UpgradeId) -> bool:
        if upgrade == UpgradeId.ZERGLINGMOVEMENTSPEED:
            return True
        elif self.tier == StrategyTier.Zero:
            return False
        elif upgrade == UpgradeId.BURROW:
            return self.tier >= StrategyTier.Hatch
        elif upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL1:
            return self.obs.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL1, include_planned=False) > 0
        elif upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL2:
            return self.obs.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL2, include_planned=False) > 0
        elif upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL3:
            return self.obs.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL3, include_planned=False) > 0
        elif upgrade in ZERG_FLYER_UPGRADES or upgrade in ZERG_FLYER_ARMOR_UPGRADES:
            return self.obs.count(UnitTypeId.GREATERSPIRE, include_planned=False) > 0
        elif upgrade == UpgradeId.OVERLORDSPEED:
            return self.tier >= StrategyTier.Lair
        else:
            return True

    def can_build(self, t: UnitTypeId) -> bool:
        return not any(self.obs.get_missing_requirements(t))

    @cached_property
    def army_composition(self) -> UnitComposition:
        # force droning up to 21
        # TODO: check if necessary
        if not self.obs.structures({UnitTypeId.SPAWNINGPOOL}).ready:
            return UnitComposition({})
        composition = self.counter_composition
        composition += {
            UnitTypeId.RAVAGER: composition[UnitTypeId.ROACH] / self.param.ravager_mixin.mean,
            UnitTypeId.CORRUPTOR: composition[UnitTypeId.BROODLORD] / self.param.corruptor_mixin.mean,
        }
        composition = UnitComposition({k: v for k, v in composition.items() if v > 0})
        if sum(composition.values()) < 1:
            composition += {UnitTypeId.ZERGLING: 1}
        elif self.flood_lings:
            composition += {UnitTypeId.ZERGLING: 100}
        can_afford_hydras = min(
            self.obs.bank.minerals / 100,
            self.obs.bank.vespene / 50,
            self.obs.bank.larva,
        )
        can_afford_lings = min(
            self.obs.bank.minerals / 50,
            self.obs.bank.larva,
        )
        can_afford_queens = self.obs.bank.minerals / 150
        if self.param.hydras_when_banking.mean < can_afford_hydras:
            composition += {UnitTypeId.HYDRALISK: can_afford_hydras}
            composition += {UnitTypeId.BROODLORD: can_afford_hydras}  # for good measure
        else:
            if self.param.lings_when_banking.mean < can_afford_lings:
                composition += {UnitTypeId.ZERGLING: can_afford_lings}
            if self.param.queens_when_banking.mean < can_afford_queens:
                composition += {UnitTypeId.QUEEN: can_afford_queens}
        return composition * self.param.counter_factor.mean

    @cached_property
    def counter_composition(self) -> UnitComposition:
        def total_cost(t: UnitTypeId) -> float:
            return self.obs.cost.of(t).total_resources

        composition = defaultdict[UnitTypeId, float](float)
        for enemy_type, count in self.enemy_composition.items():
            for counter in UNIT_COUNTER_DICT.get(enemy_type, []):
                if self.can_build(counter):
                    composition[counter] += count * total_cost(enemy_type) / total_cost(counter)
                    break
        return UnitComposition(composition)

    @cached_property
    def tier(self) -> StrategyTier:
        if self.obs.supply_workers < self.param.tier1_drone_count.mean or self.obs.townhalls.amount < 3:
            return StrategyTier.Zero
        elif self.obs.supply_workers < self.param.tier2_drone_count.mean or self.obs.townhalls.amount < 4:
            return StrategyTier.Hatch
        elif self.obs.supply_workers < self.param.tier3_drone_count.mean or self.obs.townhalls.amount < 5:
            return StrategyTier.Lair
        return StrategyTier.Hive

    @cached_property
    def macro_composition(self) -> UnitComposition:
        harvester_target = max(1.0, min(self.param.tier3_drone_count.mean, self.obs.max_harvesters))
        queen_target = max(
            0.0, min(self.param.queens_limit.mean, self.param.queens_per_hatch.mean * self.obs.townhalls.amount)
        )
        composition = UnitComposition(
            {
                UnitTypeId.DRONE: harvester_target,
                UnitTypeId.QUEEN: queen_target,
            }
        )
        if burrowed_enemies := self.obs.enemy_combatants.filter(lambda u: u.is_burrowed):
            composition += {UnitTypeId.OVERSEER: min(10, len(burrowed_enemies) // 3)}
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
            composition += {UnitTypeId.GREATERSPIRE: 1}  # TODO: check if necessary
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
        # upgrades.append(UpgradeId.ZERGLINGMOVEMENTSPEED)
        targets: set[MacroId] = set(upgrades)
        targets.update(self.composition_target.keys())
        targets.update(r for item in set(targets) for r in REQUIREMENTS[item])
        for target in targets:
            if equivalents := WITH_TECH_EQUIVALENTS.get(target):
                target_met = any(self.obs.count(t) for t in equivalents)
            else:
                target_met = bool(self.obs.count(target))
            if not target_met:
                yield MacroPlan(target, priority=self.param.tech_priority.mean)

    def expand(self) -> Iterable[MacroPlan]:
        if self.obs.time < 50:
            return
        if self.obs.townhalls.amount == 2 and self.obs.count(UnitTypeId.QUEEN, include_planned=False) < 2:
            return

        worker_max = self.obs.max_harvesters
        saturation = max(0.0, min(1.0, self.obs.supply_workers / max(1, worker_max)))
        if self.obs.townhalls.amount > 2 and saturation < 2 / 3:
            return

        priority = 3 * (saturation - 1)
        # TODO: prioritize everything on the fly
        # for plan in self.macro.planned_by_type(UnitTypeId.HATCHERY):
        #     if plan.priority < math.inf:
        #         plan.priority = priority

        if self.obs.count(UnitTypeId.HATCHERY, include_actual=False) > 0:
            return
        yield MacroPlan(UnitTypeId.HATCHERY, priority=priority)

    def morph_overlord(self) -> Iterable[MacroPlan]:
        supply = self.obs.supply_cap + self.obs.supply_pending / 2 + self.obs.supply_planned
        supply_target = min(200.0, self.obs.supply_used + 2 + 20 * self.obs.income.larva)
        if supply_target <= supply:
            return
        yield MacroPlan(UnitTypeId.OVERLORD, priority=1)
