import enum
from collections import defaultdict
from collections.abc import Iterable
from functools import total_ordering

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from phantom.common.constants import (
    SPORE_TIMINGS,
    SPORE_TRIGGERS,
    SUPPLY_PROVIDED,
    UNIT_COUNTER_DICT,
    ZERG_FLYER_ARMOR_UPGRADES,
    ZERG_FLYER_UPGRADES,
)
from phantom.common.unit_composition import UnitComposition, add_compositions, composition_of, sub_compositions
from phantom.knowledge import Knowledge
from phantom.macro.main import MacroPlan
from phantom.observation import Observation
from phantom.parameters import AgentParameters, NormalPrior

# TODO: investigate numpy versioning mismatch
# with lzma.open(Path(__file__).parent.parent.parent / "models" / "scout.pkl.xz") as f:
#     SCOUT_PREDICTOR = ScoutPredictor(pickle.load(f))
SCOUT_PREDICTOR = None


@total_ordering
class StrategyTier(enum.Enum):
    HATCH = 0
    LAIR = 1
    HIVE = 2
    LATEGAME = 3

    def __ge__(self, other):
        return self.value >= other.value


class StrategyState:
    def __init__(
        self,
        knowledge: Knowledge,
        parameters: AgentParameters,
    ) -> None:
        self.knowledge = knowledge
        self.counter_factor = parameters.normal("counter_factor", NormalPrior(2.5, 0.1))
        self.ravager_mixin = parameters.normal("ravager_mixin", NormalPrior(21, 1))
        self.corruptor_mixin = parameters.normal("corruptor_mixin", NormalPrior(13, 1))
        self.tier1_drone_count = parameters.normal("tier1_drone_count", NormalPrior(40, 1))
        self.tier2_drone_count = parameters.normal("tier2_drone_count", NormalPrior(60, 1))
        self.tier3_drone_count = parameters.normal("tier3_drone_count", NormalPrior(80, 1))
        self.tech_priority_offset = parameters.normal("tech_priority_offset", NormalPrior(-0.75, 0.1))
        self.tech_priority_scale = parameters.normal("tech_priority_scale", NormalPrior(1.0, 0.1))
        self.hydras_when_banking = parameters.normal("hydras_when_banking", NormalPrior(5, 1))
        self.lings_when_banking = parameters.normal("lings_when_banking", NormalPrior(10, 1))
        self.queens_when_banking = parameters.normal("queens_when_banking", NormalPrior(3, 1))
        self.queens_per_hatch = parameters.normal("queens_per_hatch", NormalPrior(1.5, 0.1))
        self.queens_limit = parameters.normal("queens_limit", NormalPrior(12, 1))

    def step(self, observation: Observation) -> "Strategy":
        return Strategy(self, observation)


class Strategy:
    def __init__(
        self,
        context: StrategyState,
        obs: Observation,
    ) -> None:
        self.context = context
        self.obs = obs

        self.composition = composition_of(obs.units)
        self.enemy_composition = composition_of(obs.enemy_units)
        self.enemy_composition_predicted = self._predict_enemy_composition()
        self.counter_composition = self._counter_composition()
        self.army_composition = self._army_composition()
        self.tier = self._tier()
        self.macro_composition = self._macro_composition()
        self.composition_target = add_compositions(self.macro_composition, self.army_composition)
        self.composition_deficit = sub_compositions(self.composition_target, self.composition)

    def make_tech(self) -> Iterable[MacroPlan]:
        upgrade_weights = dict[UpgradeId, float]()
        for unit, count in self.composition_target.items():
            for upgrade in self.obs.upgrades_by_unit(unit):
                upgrade_weights[upgrade] = upgrade_weights.setdefault(upgrade, 0.0) + count

        # strategy specific filter
        upgrade_weights = {k: v for k, v in upgrade_weights.items() if self.filter_upgrade(k)}

        total = sum(upgrade_weights.values())
        if total == 0:
            return

        # normalize
        upgrade_weights = {k: v / total for k, v in upgrade_weights.items()}

        for upgrade, weight in upgrade_weights.items():
            if upgrade in self.obs.upgrades or upgrade in self.obs.bot.pending_upgrades or self.obs.planned[upgrade]:
                continue
            priority = self.context.tech_priority_offset.value + self.context.tech_priority_scale.value * weight
            yield MacroPlan(upgrade, priority=priority)

    def expand(self) -> Iterable[MacroPlan]:
        worker_max = self.obs.max_harvesters
        saturation = self.obs.supply_workers / max(1, worker_max)
        saturation = max(0.0, min(1.0, saturation))

        if self.obs.townhalls.amount > 2 and saturation < 2 / 3:
            return

        priority = 3 * (saturation - 1)

        if self.obs.count_planned(UnitTypeId.HATCHERY) > 0:
            return
        if self.obs.count_pending(UnitTypeId.HATCHERY) > 1:
            return
        yield MacroPlan(UnitTypeId.HATCHERY, priority=priority)

    def make_spores(self) -> Iterable[MacroPlan]:
        if self.obs.iteration % 31 != 0:
            return

        timing = SPORE_TIMINGS[self.obs.knowledge.enemy_race]
        if self.obs.time < timing:
            return

        planned_or_pending = self.obs.count_planned(UnitTypeId.SPORECRAWLER) + self.obs.count_pending(
            UnitTypeId.SPORECRAWLER
        )
        if planned_or_pending > 0:
            return

        triggers = SPORE_TRIGGERS[self.obs.knowledge.enemy_race]
        if not self.obs.enemy_units(triggers).exists:
            return

        spore_dict = {tuple(s.position.rounded): s for s in self.obs.structures(UnitTypeId.SPORECRAWLER)}
        for base in self.obs.bases_taken:
            spore_position = self.obs.knowledge.spore_position[base]
            if tuple(spore_position.rounded) in spore_dict:
                continue
            yield MacroPlan(UnitTypeId.SPORECRAWLER, target=spore_position)

    def morph_overlord(self) -> Iterable[MacroPlan]:
        supply_planned = sum(
            provided * self.obs.planned[unit_type] for unit_type, provided in SUPPLY_PROVIDED[self.obs.bot.race].items()
        )
        supply = self.obs.supply_cap + self.obs.supply_pending / 2 + supply_planned
        supply_target = min(200.0, self.obs.supply_used + 2 + 20 * self.obs.income.larva)
        if supply_target <= supply:
            return
        yield MacroPlan(UnitTypeId.OVERLORD, priority=1)

    def can_build(self, t: UnitTypeId) -> bool:
        return not any(self.obs.get_missing_requirements(t))

    def filter_upgrade(self, upgrade: UpgradeId) -> bool:
        upgrade_set = self.obs.upgrades | self.obs.bot.pending_upgrades
        if upgrade == UpgradeId.ZERGLINGMOVEMENTSPEED:
            return True
        elif self.tier == StrategyTier.HATCH:
            return False
        elif upgrade == UpgradeId.BURROW:
            return self.tier >= StrategyTier.HATCH
        elif upgrade == UpgradeId.ZERGLINGATTACKSPEED:
            return self.tier >= StrategyTier.HIVE
        elif upgrade == UpgradeId.TUNNELINGCLAWS:
            return UpgradeId.GLIALRECONSTITUTION in upgrade_set
        elif upgrade == UpgradeId.EVOLVEGROOVEDSPINES:
            return UpgradeId.EVOLVEMUSCULARAUGMENTS in upgrade_set
        elif upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL1:
            return self.tier >= StrategyTier.LAIR
        # elif upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL2:
        #     return UpgradeId.ZERGMISSILEWEAPONSLEVEL2 in upgrade_set
        # elif upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL3:
        #     return UpgradeId.ZERGMISSILEWEAPONSLEVEL3 in upgrade_set
        elif upgrade in {UpgradeId.ZERGMISSILEWEAPONSLEVEL1, UpgradeId.ZERGMELEEWEAPONSLEVEL1}:
            return UpgradeId.ZERGGROUNDARMORSLEVEL1 in upgrade_set
        elif upgrade in {UpgradeId.ZERGMISSILEWEAPONSLEVEL2, UpgradeId.ZERGMELEEWEAPONSLEVEL2}:
            return UpgradeId.ZERGGROUNDARMORSLEVEL2 in upgrade_set
        elif upgrade in {UpgradeId.ZERGMISSILEWEAPONSLEVEL3, UpgradeId.ZERGMELEEWEAPONSLEVEL3}:
            return UpgradeId.ZERGGROUNDARMORSLEVEL3 in upgrade_set
        elif upgrade in ZERG_FLYER_UPGRADES or upgrade in ZERG_FLYER_ARMOR_UPGRADES:
            return bool(self.obs.count_actual(UnitTypeId.GREATERSPIRE)) or bool(
                self.obs.count_pending(UnitTypeId.GREATERSPIRE)
            )
        elif upgrade == UpgradeId.OVERLORDSPEED:
            return self.tier >= StrategyTier.HIVE
        else:
            return True

    def _predict_enemy_composition(self) -> UnitComposition:
        return self.enemy_composition
        # vision = PlayerVision.from_units(self.obs.units | self.obs.enemy_units)
        # enemy_vision = SCOUT_PREDICTOR.predict(self.obs.game_loop, vision, self.obs.player_races)
        # composition = UnitComposition(dict(enemy_vision.composition)) + self.enemy_composition
        # composition = UnitComposition({k: v for k, v in composition.items() if v >= 1})
        # return composition

    def _tier(self) -> StrategyTier:
        if (
            self.obs.supply_workers < self.context.tier1_drone_count.value
            or self.obs.townhalls.amount < 2
            or self.obs.time < 3 * 60
        ):
            return StrategyTier.HATCH
        elif (
            self.obs.supply_workers < self.context.tier2_drone_count.value
            or self.obs.townhalls.amount < 3
            or self.obs.time < 6 * 60
        ):
            return StrategyTier.LAIR
        elif (
            self.obs.supply_workers < self.context.tier3_drone_count.value
            or self.obs.townhalls.amount < 4
            or self.obs.time < 9 * 60
        ):
            return StrategyTier.HIVE
        return StrategyTier.LATEGAME

    def _army_composition(self) -> UnitComposition:
        # force droning up to 21
        # TODO: check if necessary
        if not self.obs.structures({UnitTypeId.SPAWNINGPOOL}).ready:
            return {}
        counter_composition = {k: self.context.counter_factor.value * v for k, v in self.counter_composition.items()}
        composition = defaultdict[UnitTypeId, float](float, counter_composition)
        corruptor_mixin = int(composition[UnitTypeId.BROODLORD] / self.context.corruptor_mixin.value)
        if corruptor_mixin > 0:
            composition[UnitTypeId.CORRUPTOR] += corruptor_mixin
        if sum(composition.values()) < 1:
            composition[UnitTypeId.ZERGLING] += 4
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
        if self.context.hydras_when_banking.value < can_afford_hydras:
            composition[UnitTypeId.HYDRALISK] += can_afford_hydras
            composition[UnitTypeId.BROODLORD] += can_afford_hydras
        else:
            if self.context.lings_when_banking.value < can_afford_lings:
                composition[UnitTypeId.ZERGLING] += can_afford_lings
            if self.context.queens_when_banking.value < can_afford_queens:
                composition[UnitTypeId.QUEEN] += can_afford_queens
        return composition

    def _counter_composition(self) -> UnitComposition:
        def total_cost(t: UnitTypeId) -> float:
            return self.context.knowledge.cost.of(t).total_resources

        composition = defaultdict[UnitTypeId, float](float)
        for enemy_type, count in self.enemy_composition_predicted.items():
            for counter in UNIT_COUNTER_DICT.get(enemy_type, []):
                if self.can_build(counter):
                    composition[counter] += count * total_cost(enemy_type) / total_cost(counter)
                    break
        return composition

    def _macro_composition(self) -> UnitComposition:
        harvester_target = min(80, max(1.0, self.obs.max_harvesters))
        queen_target = max(
            0.0, min(self.context.queens_limit.value, self.context.queens_per_hatch.value * self.obs.townhalls.amount)
        )
        composition = defaultdict[UnitTypeId, float](float)

        composition[UnitTypeId.DRONE] += harvester_target
        composition[UnitTypeId.QUEEN] += queen_target
        if self.tier >= StrategyTier.HATCH:
            composition[UnitTypeId.SPAWNINGPOOL] += 1
        if self.tier >= StrategyTier.LAIR:
            composition[UnitTypeId.LAIR] += 1
            composition[UnitTypeId.OVERSEER] += 1
            composition[UnitTypeId.ROACHWARREN] += 1
            composition[UnitTypeId.HYDRALISKDEN] += 1
            composition[UnitTypeId.EVOLUTIONCHAMBER] += 1
        if self.tier >= StrategyTier.HIVE:
            composition[UnitTypeId.INFESTATIONPIT] += 1
            composition[UnitTypeId.HIVE] += 1
            composition[UnitTypeId.OVERSEER] += 1
            composition[UnitTypeId.EVOLUTIONCHAMBER] += 1
        if self.tier >= StrategyTier.LATEGAME:
            composition[UnitTypeId.OVERSEER] += 2
            composition[UnitTypeId.SPIRE] += 1
            composition[UnitTypeId.GREATERSPIRE] += 1
        return composition
