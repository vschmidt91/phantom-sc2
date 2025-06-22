import enum
from collections import defaultdict
from collections.abc import Iterable
from functools import total_ordering

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from phantom.common.constants import (
    UNIT_COUNTER_DICT,
    WITH_TECH_EQUIVALENTS,
    ZERG_FLYER_ARMOR_UPGRADES,
    ZERG_FLYER_UPGRADES,
)
from phantom.common.unit_composition import UnitComposition
from phantom.knowledge import Knowledge
from phantom.macro.state import MacroId, MacroPlan
from phantom.observation import Observation
from phantom.parameters import AgentParameters, NormalPrior

# TODO: investigate numpy versioning mismatch
# with lzma.open(Path(__file__).parent.parent.parent / "models" / "scout.pkl.xz") as f:
#     SCOUT_PREDICTOR = ScoutPredictor(pickle.load(f))
SCOUT_PREDICTOR = None


@total_ordering
class StrategyTier(enum.Enum):
    Zero = 0
    Hatch = 1
    Lair = 2
    Hive = 3

    def __ge__(self, other):
        return self.value >= other.value


class Strategy:
    def __init__(
        self,
        context: "StrategyState",
        obs: Observation,
    ) -> None:
        self.context = context
        self.obs = obs

        self.composition = UnitComposition.of(obs.units)
        self.enemy_composition = UnitComposition.of(obs.enemy_units)
        self.enemy_composition_predicted = self._predict_enemy_composition()
        self.counter_composition = self._counter_composition()
        self.army_composition = self._army_composition()
        self.tier = self._tier()
        self.macro_composition = self._macro_composition()
        self.composition_target = self.macro_composition + self.army_composition
        self.composition_deficit = self.composition_target - self.composition

    def make_tech(self) -> Iterable[MacroPlan]:
        upgrades = [
            u
            for unit, count in self.composition_target.items()
            for u in self.obs.upgrades_by_unit(unit)
            if self.filter_upgrade(u)
        ]
        # upgrades.append(UpgradeId.ZERGLINGMOVEMENTSPEED)
        targets: set[MacroId] = set(upgrades)
        # targets.update(self.composition_target.keys())
        # targets.update(r for item in set(targets) for r in REQUIREMENTS[item])
        for target in targets:
            if equivalents := WITH_TECH_EQUIVALENTS.get(target):
                target_met = any(self.obs.count(t) for t in equivalents)
            else:
                target_met = bool(self.obs.count(target))
            if not target_met:
                yield MacroPlan(target, priority=self.context.tech_priority.value)

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

    def can_build(self, t: UnitTypeId) -> bool:
        return not any(self.obs.get_missing_requirements(t))

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

    def _predict_enemy_composition(self) -> UnitComposition:
        return self.enemy_composition
        # vision = PlayerVision.from_units(self.obs.units | self.obs.enemy_units)
        # enemy_vision = SCOUT_PREDICTOR.predict(self.obs.game_loop, vision, self.obs.player_races)
        # composition = UnitComposition(dict(enemy_vision.composition)) + self.enemy_composition
        # composition = UnitComposition({k: v for k, v in composition.items() if v >= 1})
        # return composition

    def _tier(self) -> StrategyTier:
        if self.obs.supply_workers < self.context.tier1_drone_count.value or self.obs.townhalls.amount < 2:
            return StrategyTier.Zero
        elif self.obs.supply_workers < self.context.tier2_drone_count.value or self.obs.townhalls.amount < 3:
            return StrategyTier.Hatch
        elif self.obs.supply_workers < self.context.tier3_drone_count.value or self.obs.townhalls.amount < 4:
            return StrategyTier.Lair
        return StrategyTier.Hive

    def _army_composition(self) -> UnitComposition:
        # force droning up to 21
        # TODO: check if necessary
        if not self.obs.structures({UnitTypeId.SPAWNINGPOOL}).ready:
            return UnitComposition({})
        composition = self.counter_composition
        composition += {
            UnitTypeId.RAVAGER: composition[UnitTypeId.ROACH] / self.context.ravager_mixin.value,
            UnitTypeId.CORRUPTOR: composition[UnitTypeId.BROODLORD] / self.context.corruptor_mixin.value,
        }
        composition = UnitComposition({k: v for k, v in composition.items() if v > 0})
        if sum(composition.values()) < 1:
            composition += {UnitTypeId.ZERGLING: 1}
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
            composition += {UnitTypeId.HYDRALISK: can_afford_hydras}
            composition += {UnitTypeId.BROODLORD: can_afford_hydras}  # for good measure
        else:
            if self.context.lings_when_banking.value < can_afford_lings:
                composition += {UnitTypeId.ZERGLING: can_afford_lings}
            if self.context.queens_when_banking.value < can_afford_queens:
                composition += {UnitTypeId.QUEEN: can_afford_queens}
        return composition * self.context.counter_factor.value

    def _counter_composition(self) -> UnitComposition:
        def total_cost(t: UnitTypeId) -> float:
            return self.context.knowledge.cost.of(t).total_resources

        composition = defaultdict[UnitTypeId, float](float)
        for enemy_type, count in self.enemy_composition_predicted.items():
            for counter in UNIT_COUNTER_DICT.get(enemy_type, []):
                if self.can_build(counter):
                    composition[counter] += count * total_cost(enemy_type) / total_cost(counter)
                    break
        return UnitComposition(composition)

    def _macro_composition(self) -> UnitComposition:
        harvester_target = max(1.0, self.obs.max_harvesters)
        queen_target = max(
            0.0, min(self.context.queens_limit.value, self.context.queens_per_hatch.value * self.obs.townhalls.amount)
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
            composition += {UnitTypeId.LAIR: 1}
        if self.tier >= StrategyTier.Lair:
            composition += {UnitTypeId.INFESTATIONPIT: 1}
            composition += {UnitTypeId.HIVE: 1}
            composition += {UnitTypeId.OVERSEER: 2}
            composition += {UnitTypeId.HYDRALISKDEN: 1}
            composition += {UnitTypeId.EVOLUTIONCHAMBER: 1}
        if self.tier >= StrategyTier.Hive:
            composition += {UnitTypeId.OVERSEER: 4}
            composition += {UnitTypeId.EVOLUTIONCHAMBER: 1}
            composition += {UnitTypeId.SPIRE: 1}
            composition += {UnitTypeId.GREATERSPIRE: 1}
        return composition


class StrategyState:
    def __init__(
        self,
        knowledge: Knowledge,
        parameters: AgentParameters,
    ) -> None:
        self.knowledge = knowledge
        self.counter_factor = parameters.normal("counter_factor", NormalPrior(2.0, 0.1))
        self.ravager_mixin = parameters.normal("ravager_mixin", NormalPrior(21, 1))
        self.corruptor_mixin = parameters.normal("corruptor_mixin", NormalPrior(13, 1))
        self.tier1_drone_count = parameters.normal("tier1_drone_count", NormalPrior(32, 1))
        self.tier2_drone_count = parameters.normal("tier2_drone_count", NormalPrior(48, 1))
        self.tier3_drone_count = parameters.normal("tier3_drone_count", NormalPrior(66, 1))
        self.tech_priority = parameters.normal("tech_priority", NormalPrior(-0.25, 0.1))
        self.hydras_when_banking = parameters.normal("hydras_when_banking", NormalPrior(5, 1))
        self.lings_when_banking = parameters.normal("lings_when_banking", NormalPrior(10, 1))
        self.queens_when_banking = parameters.normal("queens_when_banking", NormalPrior(3, 1))
        self.queens_per_hatch = parameters.normal("queens_per_hatch", NormalPrior(1.5, 0.1))
        self.queens_limit = parameters.normal("queens_limit", NormalPrior(12, 1))

    def step(self, observation: Observation) -> Strategy:
        return Strategy(self, observation)
