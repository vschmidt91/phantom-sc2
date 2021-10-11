
import math
import itertools, random

from s2clientprotocol.error_pb2 import QueueIsFull
from s2clientprotocol.sc2api_pb2 import Macro
from macro_objective import MacroObjective
from s2clientprotocol.raw_pb2 import Unit
from typing import List, Coroutine, Dict, Union

from cost import Cost
from sc2 import AbilityId, game_info
from sc2 import unit
from sc2.game_data import AbilityData
from sc2.ids import upgrade_id
from sc2.units import Units
from build_order import Hatch16, Pool12, Pool16
from timer import run_timed

from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO

from common import CommonAI
from utils import CHANGELINGS, armyValue, filterArmy, makeUnique, withEquivalents, unitValue, choose_by_distance_to
from unit_counters import UNIT_COUNTERS

MELEE_UPGRADES = [
    UpgradeId.ZERGMELEEWEAPONSLEVEL1,
    UpgradeId.ZERGMELEEWEAPONSLEVEL2,
    UpgradeId.ZERGMELEEWEAPONSLEVEL3,
]

ARMOR_UPGRADES = [
    UpgradeId.ZERGGROUNDARMORSLEVEL1,
    UpgradeId.ZERGGROUNDARMORSLEVEL2,
    UpgradeId.ZERGGROUNDARMORSLEVEL3,
]

RANGED_UPGRADES = [
    UpgradeId.ZERGMISSILEWEAPONSLEVEL1,
    UpgradeId.ZERGMISSILEWEAPONSLEVEL2,
    UpgradeId.ZERGMISSILEWEAPONSLEVEL3,
]

FLYER_UPGRADES = [
    UpgradeId.ZERGFLYERWEAPONSLEVEL1,
    UpgradeId.ZERGFLYERWEAPONSLEVEL2,
    UpgradeId.ZERGFLYERWEAPONSLEVEL3,
]

FLYER_ARMOR_UPGRADES = [
    UpgradeId.ZERGFLYERARMORSLEVEL1,
    UpgradeId.ZERGFLYERARMORSLEVEL2,
    UpgradeId.ZERGFLYERARMORSLEVEL3,
]

HATCH_FIRST = [
    UnitTypeId.DRONE,
    UnitTypeId.OVERLORD,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.HATCHERY,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.EXTRACTOR,
    UnitTypeId.SPAWNINGPOOL,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.OVERLORD,
    UpgradeId.ZERGLINGMOVEMENTSPEED,
    UnitTypeId.QUEEN,
    UnitTypeId.QUEEN,
    # UnitTypeId.ZERGLING,
    # UnitTypeId.ZERGLING,
]

POOL_FIRST = [
    UnitTypeId.DRONE,
    UnitTypeId.OVERLORD,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.SPAWNINGPOOL,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.HATCHERY,
    UnitTypeId.DRONE,
    UnitTypeId.ZERGLING,
    UnitTypeId.ZERGLING,
    UnitTypeId.ZERGLING,
    UnitTypeId.QUEEN,
    UnitTypeId.EXTRACTOR,
    UnitTypeId.OVERLORD,
]

CREEP_RANGE = 10

class ZergAI(CommonAI):

    def __init__(self, **kwargs):
        super(self.__class__, self).__init__(**kwargs)
        self.composition = {}
        self.buildOrder = HATCH_FIRST
        self.goLair = False
        self.goHive = False
        self.macroObjectives = []
        self.gasTarget = 0
        self.timings_acc = {}
        self.timings_interval = 64
        self.tumors_inactive = set()

    async def on_unit_created(self, unit: Unit):
        if unit.type_id is UnitTypeId.OVERLORD and self.structures(withEquivalents(UnitTypeId.LAIR)).exists:
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

    async def on_step(self, iteration):

        steps = {
            # self.update_pending: 1,
            self.followBuildOrder: 1,
            self.adjustComposition: 1,
            self.microQueens: 1,
            self.spreadCreep: 4,
            self.moveOverlord: 4,
            self.changelingScout: 8,
            self.morphOverlords: 8,
            self.adjustGasTarget: 1,
            self.morphUnits: 16,
            self.buildGasses: 1,
            self.trainQueens: 4,
            self.techBuildings: 16,
            self.upgrade: 8,
            self.techUp: 8,
            self.expandIfNecessary: 8,
            # self.buildSpores: 1,
            self.micro: 1,
            self.assignWorker: 4,
            self.reachMacroObjective: 4,
        }

        steps_filtered = [s for s, m in steps.items() if iteration % m == 0]
        timings = await run_timed(steps_filtered)
            
        for key, value in timings.items():
            self.timings_acc[key] = self.timings_acc.get(key, 0) + value

        if iteration % self.timings_interval == 0:
            timings_items = ((k, round(1e3 * n / self.timings_interval, 1)) for k, n in self.timings_acc.items())
            timings_sorted = dict(sorted(timings_items, key=lambda p : p[1], reverse=True))
            print(timings_sorted)
            self.timings_acc = {}

        # if iteration % 100 == 0:
        #     print(sum(self.enemies.values()), sum(unitValue(u) for u in self.units))

    def followBuildOrder(self):
        if not self.buildOrder:
            return
        if self.macroObjectives:
            return
        target = self.buildOrder.pop(0)
        self.macroObjectives.append(MacroObjective(target))

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
        if self.buildOrder:
            return
        upgrades_want = set()
        if UnitTypeId.ZERGLING in self.composition:
            upgrades_want.add(UpgradeId.ZERGLINGMOVEMENTSPEED)
            if self.goHive:
                upgrades_want.add(UpgradeId.ZERGLINGATTACKSPEED)
            upgrades_want.update(self.upgradeSequence(MELEE_UPGRADES))
            upgrades_want.update(self.upgradeSequence(ARMOR_UPGRADES))
        if UnitTypeId.ULTRALISK in self.composition:
            upgrades_want.add(UpgradeId.CHITINOUSPLATING)
            upgrades_want.add(UpgradeId.ANABOLICSYNTHESIS)
            upgrades_want.update(self.upgradeSequence(MELEE_UPGRADES))
            upgrades_want.update(self.upgradeSequence(ARMOR_UPGRADES))
        if UnitTypeId.BANELING in self.composition:
            upgrades_want.add(UpgradeId.CENTRIFICALHOOKS)
            upgrades_want.update(self.upgradeSequence(MELEE_UPGRADES))
            upgrades_want.update(self.upgradeSequence(ARMOR_UPGRADES))
        if UnitTypeId.ROACH in self.composition:
            upgrades_want.add(UpgradeId.GLIALRECONSTITUTION)
            upgrades_want.update(self.upgradeSequence(RANGED_UPGRADES))
            upgrades_want.update(self.upgradeSequence(ARMOR_UPGRADES))
        if UnitTypeId.HYDRALISK in self.composition:
            upgrades_want.add(UpgradeId.EVOLVEGROOVEDSPINES)
            upgrades_want.add(UpgradeId.EVOLVEMUSCULARAUGMENTS)
            upgrades_want.update(self.upgradeSequence(RANGED_UPGRADES))
            upgrades_want.update(self.upgradeSequence(ARMOR_UPGRADES))
        if UnitTypeId.MUTALISK in self.composition:
            upgrades_want.update(self.upgradeSequence(FLYER_UPGRADES))
            upgrades_want.update(self.upgradeSequence(FLYER_ARMOR_UPGRADES))
        if UnitTypeId.CORRUPTOR in self.composition:
            upgrades_want.update(self.upgradeSequence(FLYER_UPGRADES))
            upgrades_want.update(self.upgradeSequence(FLYER_ARMOR_UPGRADES))
        if UnitTypeId.BROODLORD in self.composition:
        #     upgrades_want.update(self.upgradeSequence(FLYER_ARMOR_UPGRADES))
            upgrades_want.update(self.upgradeSequence(MELEE_UPGRADES))
            upgrades_want.update(self.upgradeSequence(ARMOR_UPGRADES))
        if UnitTypeId.OVERSEER in self.composition:
            upgrades_want.add(UpgradeId.OVERLORDSPEED)

        # targets = set(targets)
        # targets = { t for t in targets if not self.already_pending_upgrade(t) }
        # pendingUpgrades = self.state.upgrades | set(t.item for t in self.macroObjectives)
        # pendingUpgrades = { t for t in pendingUpgrades if type(t) is UpgradeId }
        # targets = targets.difference(pendingUpgrades)

        for upgrade in upgrades_want:
            if self.count(upgrade) < 1:
                self.macroObjectives.append(MacroObjective(upgrade))
                return

    def upgradeSequence(self, upgrades) -> List[UpgradeId]:
        for upgrade in upgrades:
            if upgrade not in self.state.upgrades:
                return [upgrade]
        return []

    def techBuildings(self):

        if self.buildOrder:
            return

        structures_want = set()
        if UnitTypeId.ZERGLING in self.composition:
            structures_want.add(UnitTypeId.SPAWNINGPOOL)
        if (UnitTypeId.ROACH in self.composition or UnitTypeId.RAVAGER in self.composition):
            structures_want.add(UnitTypeId.ROACHWARREN)
        if UnitTypeId.BANELING in self.composition:
            structures_want.add(UnitTypeId.BANELINGNEST)
        if (UnitTypeId.HYDRALISK in self.composition or UnitTypeId.LURKER in self.composition):
            structures_want.add(UnitTypeId.HYDRALISKDEN)
        if (UnitTypeId.MUTALISK in self.composition or UnitTypeId.CORRUPTOR in self.composition or UnitTypeId.BROODLORD in self.composition):
            structures_want.add(UnitTypeId.SPIRE)
        if UnitTypeId.BROODLORD in self.composition:
            structures_want.add(UnitTypeId.GREATERSPIRE)
        if UnitTypeId.ULTRALISK in self.composition:
            structures_want.add(UnitTypeId.ULTRALISKCAVERN)

        structures_have = self.structures(structures_want)
        for structure in structures_want:
            if structures_have(structure).exists:
                continue
            elif self.count(structure):
                continue
            else:
                self.macroObjectives.append(MacroObjective(structure))
                return

    async def changelingScout(self):
        overseers = self.units(withEquivalents(UnitTypeId.OVERSEER))
        if overseers.exists:
            overseer = overseers.random
            ability = TRAIN_INFO[overseer.type_id][UnitTypeId.CHANGELING]["ability"]
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

        # overseers_idle = self.units(UnitTypeId.OVERSEER).idle
        # if overseers_idle.exists:
        #     overseer = overseers_idle.random
        #     target = self.units.random
        #     overseer.move(target.position)

    def techUp(self):
        if self.buildOrder:
            return
        if self.goLair:
            if self.count(UnitTypeId.EVOLUTIONCHAMBER) < 1:
                self.macroObjectives.append(MacroObjective(UnitTypeId.EVOLUTIONCHAMBER))
            if self.count(withEquivalents(UnitTypeId.LAIR)) < 1:
                self.macroObjectives.append(MacroObjective(UnitTypeId.LAIR))
        else:
            self.goLair |= UnitTypeId.BANELING in self.composition
            self.goLair |= UnitTypeId.ROACH in self.composition
            self.goLair |= UnitTypeId.HYDRALISK in self.composition
            self.goLair |= UnitTypeId.MUTALISK in self.composition
            self.goLair |= UnitTypeId.CORRUPTOR in self.composition
            self.goLair |= UpgradeId.ZERGMISSILEWEAPONSLEVEL1 in self.state.upgrades
            self.goLair |= UpgradeId.ZERGMELEEWEAPONSLEVEL1 in self.state.upgrades
            self.goLair |= UpgradeId.ZERGGROUNDARMORSLEVEL1 in self.state.upgrades
            self.goLair |= self.goHive
        if self.goHive:
            if self.count(withEquivalents(UnitTypeId.HIVE)) < 1:
                if self.count(UnitTypeId.INFESTATIONPIT) < 1:
                    self.macroObjectives.append(MacroObjective(UnitTypeId.INFESTATIONPIT))
                else:
                    self.macroObjectives.append(MacroObjective(UnitTypeId.HIVE))
            if self.count(UnitTypeId.EVOLUTIONCHAMBER) < 2:
                self.macroObjectives.append(MacroObjective(UnitTypeId.EVOLUTIONCHAMBER))
        else:
            self.goHive |= UnitTypeId.ULTRALISK in self.composition
            self.goHive |= UnitTypeId.BROODLORD in self.composition
            self.goHive |= UpgradeId.ZERGMISSILEWEAPONSLEVEL2 in self.state.upgrades
            self.goHive |= UpgradeId.ZERGMELEEWEAPONSLEVEL2 in self.state.upgrades
            self.goHive |= UpgradeId.ZERGGROUNDARMORSLEVEL2 in self.state.upgrades
            self.goHive |= UpgradeId.ZERGFLYERARMORSLEVEL2 in self.state.upgrades
            self.goHive |= UpgradeId.ZERGFLYERARMORSLEVEL2 in self.state.upgrades

    async def spreadCreep(self, spreader: Unit = None, numAttempts: int = 5):
        
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
        targets = [
            *self.expansion_locations_list,
            *(r.top_center for r in self.game_info.map_ramps),
            self.game_info.map_center,
        ]

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

        if spreader.build(UnitTypeId.CREEPTUMOR, tumorPlacement):
            self.tumors_inactive.add(spreader.tag)

    def buildSpores(self):
        if self.buildOrder:
            return
        sporeTime = {
            Race.Zerg: 8 * 60,
            Race.Protoss: 5 * 60,
            Race.Terran: 5 * 60,
        }
        if (
            sporeTime[self.enemy_race] < self.time
            and self.count(UnitTypeId.SPORECRAWLER) < self.townhalls.amount
        ):
            self.macroObjectives.append(MacroObjective(UnitTypeId.SPORECRAWLER))

    async def microQueens(self):

        queens = self.units(UnitTypeId.QUEEN).sorted(key=lambda q: q.tag)
        townhalls = self.townhalls.sorted(key=lambda h: h.tag)
        
        for i, queen in enumerate(queens):
            if i < len(queens) - 1 and i < self.townhalls.amount:
                townhall = townhalls[i]
            else:
                townhall = None
            if not queen.is_idle:
                continue
            elif queen.energy < 25:
                if townhall and 5 < queen.distance_to(townhall):
                    queen.attack(townhall.position)
            elif not townhall:
                await self.spreadCreep(spreader=queen)
            elif townhall.is_ready:
                queen(AbilityId.EFFECT_INJECTLARVA, townhall)

            # abilities = await self.get_available_abilities(queen)
            # if AbilityId.BUILD_CREEPTUMOR_QUEEN in abilities and 7 < self.larva.amount and random.random() < math.exp(-.03*self.count(UnitTypeId.CREEPTUMORBURROWED)):
            #     await self.spreadCreep(spreader=queen)
            # elif AbilityId.EFFECT_INJECTLARVA in abilities and hatchery.is_ready:
            #     queen(AbilityId.EFFECT_INJECTLARVA, hatchery)
            # elif 5 < queen.distance_to(hatchery):
            #     queen.attack(hatchery.position)

    def adjustComposition(self):
        workersTarget = min(80, self.getMaxWorkers())
        self.composition = { UnitTypeId.DRONE: workersTarget }
        self.composition[UnitTypeId.OVERSEER] = 1
        if self.townhalls.amount < 3:
            pass
        elif not self.goLair:
            self.composition[UnitTypeId.ROACH] = 60
            # self.composition[UnitTypeId.ZERGLING] = 50
        elif not self.goHive:
            self.composition[UnitTypeId.ROACH] = 40
            self.composition[UnitTypeId.HYDRALISK] = 40
            # self.composition[UnitTypeId.HYDRALISK] = 20
            # self.composition[UnitTypeId.ZERGLING] = 40
            # self.composition[UnitTypeId.BANELING] = 40
        else:
            self.composition[UnitTypeId.BROODLORD] = 20
            self.composition[UnitTypeId.HYDRALISK] = 40
            self.composition[UnitTypeId.ROACH] = 20
        # else:
        #     self.composition[UnitTypeId.ZERGLING] = 4
        # if 5 <= self.townhalls.amount:
        #     self.composition[UnitTypeId.CORRUPTOR] = workersTarget
        # if 6 <= self.townhalls.amount:
        #     self.composition[UnitTypeId.BROODLORD] = workersTarget

    def adjustGasTarget(self):
        cost_minerals = 0
        cost_vespene = 0
        for t, n in self.composition.items():
            cost = self.calculate_cost(t)
            cost_minerals += n * cost.minerals
            cost_vespene += n * cost.vespene
        minerals = max(0, cost_minerals - self.minerals)
        vespene = max(0, cost_vespene - self.vespene)
        gasRatio = vespene / max(1, vespene + minerals)
        self.gasTarget = 3 + int(gasRatio * self.workers.amount)

    def buildGasses(self):
        if self.buildOrder:
            return
        gasActual = self.gas_buildings.filter(lambda v : v.has_vespene).amount
        # gasPending = self.already_pending(UnitTypeId.EXTRACTOR) + sum(1 for t in self.macroObjectives if t.item is UnitTypeId.EXTRACTOR)
        gasPending = sum(1 for t in self.macroObjectives if t.item is UnitTypeId.EXTRACTOR)
        gasNeeded = max(0, int(math.ceil(self.gasTarget / 3)) - (gasActual + gasPending))
        if 0 < gasNeeded:
            self.macroObjectives.append(MacroObjective(UnitTypeId.EXTRACTOR))
    
    def trainQueens(self):
        if self.buildOrder:
            return
        queenTarget = min(6, 2 * self.townhalls.amount)
        queenPending = sum(1 for o in self.macroObjectives if o.item is UnitTypeId.QUEEN)
        queenTrainer = self.townhalls
        queenTrainer = queenTrainer.filter(lambda t : not t.is_idle)
        queenTrainer = queenTrainer.filter(lambda t : t.orders[0].ability.id is AbilityId.TRAINQUEEN_QUEEN)
        queenPending += queenTrainer.amount
        queenActual = self.units(UnitTypeId.QUEEN).amount
        if queenActual + queenPending < queenTarget:
            self.macroObjectives.append(MacroObjective(UnitTypeId.QUEEN))

    def morphOverlords(self):
        if self.buildOrder:
            return
        if self.supply_cap == 200:
            return
        if self.supply_left + self.getSupplyPending() < self.getSupplyBuffer():
            self.macroObjectives.append(MacroObjective(UnitTypeId.OVERLORD))

    def expandIfNecessary(self, max_pending = 1, saturation_target = 0.8):
        if self.buildOrder:
            return
        pendingCount = (
            self.count_pending(UnitTypeId.HATCHERY) +
            sum(1 for t in self.macroObjectives if t.item is UnitTypeId.HATCHERY) +
            sum(1 for h in self.townhalls if h.build_progress < 1))
        if pendingCount < max_pending and saturation_target * self.composition[UnitTypeId.DRONE] < self.workers.amount:
            self.macroObjectives.append(MacroObjective(UnitTypeId.HATCHERY))

    def morphUnits(self):

        if self.buildOrder:
            return

        if self.supply_used == 200:
            return

        composition_ratio = {
            unit: self.count(unit) / max(1, n)
            for unit, n in self.composition.items()
        }

        for unit, ratio in sorted(composition_ratio.items(), key=lambda p : p[1]):

            n = 5

            if 0 < self.count_planned(unit):
                continue

            if 1 <= ratio:
                continue

            self.macroObjectives.extend((MacroObjective(unit, -1) for i in range(n)))

            trainer = sorted(UNIT_TRAINED_FROM[unit], key=lambda v:v.value)[0]
            if not self.isStructure(trainer) and trainer is not UnitTypeId.LARVA:
                self.macroObjectives.extend((MacroObjective(trainer, -1) for i in range(n)))