
import math
import itertools, random
import build

from constants import ZERG_ARMOR_UPGRADES, HATCH_FIRST, ZERG_MELEE_UPGRADES, ZERG_RANGED_UPGRADES, ZERG_FLYER_UPGRADES, ZERG_FLYER_ARMOR_UPGRADES
from cost import Cost
from macro_target import MacroTarget
from typing import Counter, Iterable, List, Coroutine, Dict, Set, Union, Tuple

from timer import run_timed

from sc2 import AbilityId
from sc2.unit import Unit
from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO

from constants import CHANGELINGS, SUPPLY_PROVIDED
from common import CommonAI
from utils import withEquivalents, choose_by_distance_to
from unit_counters import UNIT_COUNTERS

CREEP_RANGE = 10
CREEP_ENABLED = True

SPORE_TIMING = {
    Race.Zerg: 7 * 60,
    Race.Protoss: 4.5 * 60,
    Race.Terran: 4.5 * 60,
}

class ZergAI(CommonAI):

    def __init__(self, build_order=HATCH_FIRST, **kwargs):
        super(self.__class__, self).__init__(**kwargs)
        self.macro_targets.extend(MacroTarget(step, 10) for step in build_order)
        self.composition = dict()
        self.timings_acc = dict()
        self.abilities = dict()
        self.timings_interval = 64

    async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId):
        if unit.type_id == UnitTypeId.LAIR:
            ability = AbilityId.BEHAVIOR_GENERATECREEPON
            for overlord in self.units(UnitTypeId.OVERLORD):
                if ability in await self.get_available_abilities(overlord):
                    overlord(ability)
                    
        # elif unit.type_id == UnitTypeId.EGG:
        #     unit_morph = UNIT_BY_TRAIN_ABILITY[unit.orders[0].ability.id]
        #     self.supply_pending += SUPPLY_PROVIDED.get(unit_morph, 0)

        await super().on_unit_type_changed(unit, previous_type)

    async def on_unit_created(self, unit: Unit):
        if unit.type_id is UnitTypeId.OVERLORD:
            if self.structures(withEquivalents(UnitTypeId.LAIR)).exists:
                unit(AbilityId.BEHAVIOR_GENERATECREEPON)
        await super(self.__class__, self).on_unit_created(unit)

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float):
        if unit.type_id == UnitTypeId.OVERLORD:
            enemies = self.enemy_units | self.enemy_structures
            if enemies.exists:
                enemy = enemies.closest_to(unit)
                unit.move(unit.position.towards(enemy.position, -20))
            else:
                unit.move(unit.position.towards(self.start_location, 20))
        await super(self.__class__, self).on_unit_took_damage(unit, amount_damage_taken)

    async def update_abilities(self):
        self.abilities.clear()
        for unit, abilties in zip(self.all_own_units, await self.get_available_abilities(self.all_own_units)):
            units = self.abilities.setdefault(unit.type_id, dict())
            units[unit.tag] = abilties

    async def on_step(self, iteration):

        await super().on_step(iteration)

        steps = {
            self.update_tables: 1,
            # self.update_abilities: 1,
            # self.update_pending: 1,
            self.adjustComposition: 4,
            self.microQueens: 1,
            self.spreadCreep: 4,
            self.moveOverlord: 4,
            self.changelingScout: 1,
            self.morphOverlords: 1,
            self.adjustGasTarget: 4,
            self.morphUnits: 1,
            self.buildGasses: 10,
            # self.trainQueens: 4,
            # self.tech: 4,
            self.upgrade: 1,
            self.expandIfNecessary: 4,
            self.micro: 1,
            self.assignWorker: 1,
            self.macro: 4,
        }

        steps_filtered = [s for s, m in steps.items() if iteration % m == 0]
        timings = await run_timed(steps_filtered)
            
        for key, value in timings.items():
            self.timings_acc[key] = self.timings_acc.get(key, 0) + value

        if iteration % self.timings_interval == 0:
            timings_items = ((k, round(1e3 * n / self.timings_interval, 1)) for k, n in self.timings_acc.items())
            timings_sorted = dict(sorted(timings_items, key=lambda p : p[1], reverse=True))
            print(timings_sorted)
            # print(self.pending)
            # print(len(self.macroObjectives))
            self.timings_acc = {}

        # if iteration % 100 == 0:
        #     print(sum(self.enemies.values()), sum(unitValue(u) for u in self.units))


    def counterComposition(self, enemies: Dict[UnitTypeId, int]) -> Dict[UnitTypeId, int]:

        enemyValue = sum((self.unitValue(u) * n for u, n in enemies.items()))
        if enemyValue == 0:
            return {}, []
        weights = {
            u: sum((w * self.unitValue(v) * enemies[v] for v, w in vw.items()))
            for u, vw in UNIT_COUNTERS.items()
        }
        techTargets = []
        composition = {}
        weights = sorted(weights.items(), key=lambda p: p[1], reverse=True)
        for u, w in weights:
            if 0 < self.getTechDistance(u):
                techTargets.append(u)
                continue
            elif w <= 0 and 0 < len(composition):
                break
            composition[u] = max(1, w)
        weightSum = sum(composition.values())
        composition = {
            u: math.ceil((w  / weightSum) * (enemyValue / self.unitValue(u)))
            for u, w in composition.items()
        }

        return composition, techTargets

    def upgrade(self):

        targets = set()
        if UnitTypeId.ZERGLING in self.composition:
            targets.add(UpgradeId.ZERGLINGMOVEMENTSPEED)
            if self.count(UnitTypeId.HIVE):
                targets.add(UpgradeId.ZERGLINGATTACKSPEED)
            targets.update(self.upgradeSequence(ZERG_MELEE_UPGRADES))
            targets.update(self.upgradeSequence(ZERG_ARMOR_UPGRADES))
        if UnitTypeId.ULTRALISK in self.composition:
            targets.add(UpgradeId.CHITINOUSPLATING)
            targets.add(UpgradeId.ANABOLICSYNTHESIS)
            targets.update(self.upgradeSequence(ZERG_MELEE_UPGRADES))
            targets.update(self.upgradeSequence(ZERG_ARMOR_UPGRADES))
        if UnitTypeId.BANELING in self.composition:
            targets.add(UpgradeId.CENTRIFICALHOOKS)
            targets.update(self.upgradeSequence(ZERG_MELEE_UPGRADES))
            targets.update(self.upgradeSequence(ZERG_ARMOR_UPGRADES))
        if UnitTypeId.ROACH in self.composition:
            targets.add(UpgradeId.GLIALRECONSTITUTION)
            targets.update(self.upgradeSequence(ZERG_RANGED_UPGRADES))
            targets.update(self.upgradeSequence(ZERG_ARMOR_UPGRADES))
        if UnitTypeId.HYDRALISK in self.composition:
            targets.add(UpgradeId.EVOLVEGROOVEDSPINES)
            targets.add(UpgradeId.EVOLVEMUSCULARAUGMENTS)
            targets.update(self.upgradeSequence(ZERG_RANGED_UPGRADES))
            targets.update(self.upgradeSequence(ZERG_ARMOR_UPGRADES))
        if UnitTypeId.MUTALISK in self.composition:
            targets.update(self.upgradeSequence(ZERG_FLYER_UPGRADES))
            targets.update(self.upgradeSequence(ZERG_FLYER_ARMOR_UPGRADES))
        if UnitTypeId.CORRUPTOR in self.composition:
            targets.update(self.upgradeSequence(ZERG_FLYER_UPGRADES))
            targets.update(self.upgradeSequence(ZERG_FLYER_ARMOR_UPGRADES))
        if UnitTypeId.BROODLORD in self.composition:
            if self.count(UnitTypeId.GREATERSPIRE, include_pending=False, include_planned=False):
                targets.update(self.upgradeSequence(ZERG_FLYER_ARMOR_UPGRADES))
                targets.update(self.upgradeSequence(ZERG_MELEE_UPGRADES))
                targets.update(self.upgradeSequence(ZERG_ARMOR_UPGRADES))
        if UnitTypeId.OVERSEER in self.composition:
            targets.add(UpgradeId.OVERLORDSPEED)

        # targets = {
        #     target
        #     for target in targets
        #     # if not self.count(upgrade)
        # }

        requirements = {
            requirement
            for upgrade in itertools.chain(targets, self.composition.keys())
            for requirement in self.get_requirements(upgrade)
        }
        targets.update(requirements)

        for target in targets:
            if not self.count(target):
                self.macro_targets.append(MacroTarget(target, 1))

        # self.tech_targets.update(upgrades_want)
        # self.tech_targets.update(self.composition.keys())


    def upgradeSequence(self, upgrades) -> Iterable[UpgradeId]:
        for upgrade in upgrades:
            if upgrade not in self.state.upgrades:
                return (upgrade,)
        return tuple()

    async def changelingScout(self):
        overseers = self.units(withEquivalents(UnitTypeId.OVERSEER))
        if overseers.exists:
            overseer = overseers.random
            ability = AbilityId.SPAWNCHANGELING_SPAWNCHANGELING
            if ability in await self.get_available_abilities(overseer):
                overseer(ability)
        changelings = self.units(CHANGELINGS).idle
        if changelings.exists:
            changeling = changelings.random
            target = random.choice(self.expansion_locations_list)
            changeling.move(target)

    def moveOverlord(self):

        overlords = self.units(UnitTypeId.OVERLORD)
        targets = self.structures
        # targets = targets.filter(lambda s : not s.is_idle)
        overlords_idle = overlords.idle
        if overlords_idle.exists and targets.exists:
            unit = overlords_idle.random
            target = targets.random
            if 1 < unit.distance_to(target):
                unit.move(target.position)

    async def spreadCreep(self, spreader: Unit = None, numAttempts: int = 5):

        if not CREEP_ENABLED:
            return
        
        # find spreader
        if not spreader:
            tumors = self.structures(UnitTypeId.CREEPTUMORBURROWED)
            if not tumors.exists:
                return
            tumor_abilities = await self.get_available_abilities(self.structures(UnitTypeId.CREEPTUMORBURROWED))
            for tumor, abilities in zip(tumors, tumor_abilities):
                if not AbilityId.BUILD_CREEPTUMOR_TUMOR in abilities:
                    continue
                spreader = tumor
                break

        if spreader is None:
            return

        # find target
        targets = (
            *self.expansion_locations_list,
            *(r.top_center for r in self.game_info.map_ramps),
        )

        targets = [t for t in targets if not self.has_creep(t)]
        if not targets:
            return
        
        target = choose_by_distance_to(targets, spreader)
        target = spreader.position.towards(target, CREEP_RANGE)

        tumorPlacement = None
        for _ in range(numAttempts):
            position = await self.find_placement(AbilityId.ZERGBUILD_CREEPTUMOR, target)
            if position is None:
                continue
            if self.isBlockingExpansion(position):
                continue
            tumorPlacement = position
            break
        if tumorPlacement is None:
            return

        spreader.build(UnitTypeId.CREEPTUMOR, tumorPlacement)

    def buildSpores(self):
        # if self.buildOrder:
        #     return
        sporeTime = {
            Race.Zerg: 8 * 60,
            Race.Protoss: 5 * 60,
            Race.Terran: 5 * 60,
        }
        if (
            sporeTime[self.enemy_race] < self.time
            and self.count(UnitTypeId.SPORECRAWLER) < self.townhalls.amount
        ):
            self.macro_targets.append(MacroTarget(UnitTypeId.SPORECRAWLER))

    async def microQueens(self):

        queens = self.units(UnitTypeId.QUEEN).sorted_by_distance_to(self.start_location)
        townhalls = self.townhalls.sorted_by_distance_to(self.start_location)
        
        for i, queen in enumerate(queens):
            if self.townhalls.amount <= i:
                townhall = None
            elif 2 < len(queens) and i == len(queens) - 1:
                townhall = None
            else:
                townhall = townhalls[i]
            if not queen.is_idle:
                continue
            elif queen.energy < 25:
                if townhall and 5 < queen.distance_to(townhall):
                    queen.attack(townhall.position)
            elif not townhall:
                await self.spreadCreep(spreader=queen)
            elif townhall.is_ready:
                queen(AbilityId.EFFECT_INJECTLARVA, townhall)

    def adjustComposition(self):

        workers_target = min(80, self.getMaxWorkers())
        queens_target = min(5, 1 + self.townhalls.amount)
        self.composition = {
            UnitTypeId.DRONE: workers_target,
            UnitTypeId.QUEEN: queens_target,
        }

        if SPORE_TIMING[self.enemy_race] < self.time:
            self.composition[UnitTypeId.SPORECRAWLER] = self.townhalls.ready.amount

        # supply_left = 200 - self.composition[UnitTypeId.DRONE] - 2 * self.composition[UnitTypeId.QUEEN]

        if self.townhalls.amount < 4:
            pass
        # elif self.townhalls.amount < 4:
        #     self.composition[UnitTypeId.ROACH] = 8
        elif (
            not self.count(UnitTypeId.LAIR, include_pending=False, include_planned=False)
            and not self.count(UnitTypeId.HIVE, include_pending=False, include_planned=False)
        ):
            self.composition[UnitTypeId.ROACH] = 60
        elif not self.count(UnitTypeId.HIVE, include_pending=False, include_planned=False):
            self.composition[UnitTypeId.OVERSEER] = 1
            self.composition[UnitTypeId.HYDRALISK] = 20
            self.composition[UnitTypeId.ROACH] = 40
            # self.composition[UnitTypeId.BANELING] = 40
            # self.composition[UnitTypeId.HYDRALISK] = 40
        else:
            self.composition[UnitTypeId.OVERSEER] = 2
            self.composition[UnitTypeId.HYDRALISK] = 40
            self.composition[UnitTypeId.ROACH] = 40
            if self.count(UnitTypeId.GREATERSPIRE, include_pending=False, include_planned=False):
                self.composition[UnitTypeId.CORRUPTOR] = 10
                self.composition[UnitTypeId.BROODLORD] = 10
            else:
                self.composition[UnitTypeId.BROODLORD] = 1

    def adjustGasTarget(self):

        cost_zero = Cost(0, 0, 0)
        cost_sum = sum((target.cost or cost_zero for target in self.macro_targets), cost_zero)

        minerals = max(0, cost_sum.minerals - self.minerals)
        vespene = max(0, cost_sum.vespene - self.vespene)
        gasRatio = vespene / max(1, vespene + minerals)
        self.gas_target = gasRatio * self.count(UnitTypeId.DRONE)
        # self.gasTarget = 3 * int(self.gasTarget / 3)
        # print(self.gasTarget)

    def buildGasses(self):
        gas_depleted = self.gas_buildings.filter(lambda g : not g.has_vespene).amount
        gas_have = self.count(UnitTypeId.EXTRACTOR) - gas_depleted
        gas_max = sum(1 for g in self.get_owned_geysers())
        gas_want = min(gas_max, int(self.gas_target / 3))
        if gas_have < gas_want:
            self.macro_targets.append(MacroTarget(UnitTypeId.EXTRACTOR, 1))

    def morphOverlords(self):
        if 200 <= self.supply_cap:
            return
        supply_pending = sum(
            provided * self.count(unit, include_actual=False)
            for unit, provided in SUPPLY_PROVIDED.items()
        )
        if 200 <= self.supply_cap + supply_pending:
            return
        if self.supply_left + supply_pending < self.getSupplyBuffer():
            self.macro_targets.append(MacroTarget(UnitTypeId.OVERLORD, 1))

    def expandIfNecessary(self):
        
        worker_max = self.getMaxWorkers()
        if (
            not self.count(UnitTypeId.HATCHERY, include_actual=False)
            and not self.townhalls.not_ready.exists
            and worker_max <= self.count(UnitTypeId.DRONE)
        ):
            self.macro_targets.append(MacroTarget(UnitTypeId.HATCHERY, 1))

    def morphUnits(self):
        

        if self.supply_used == 200:
            return

        composition_missing = {
            unit: count - self.count(unit)
            for unit, count in self.composition.items()
        }

        targets = [
            MacroTarget(unit, -(i - 1) / count)
            for unit, count in composition_missing.items()
            for i in range(count)
        ]

        self.macro_targets.extend(targets)