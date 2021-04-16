
import math
import itertools, random
from reserve import Reserve
from s2clientprotocol.raw_pb2 import Unit
from typing import List, Coroutine, Dict, Union

from sc2 import AbilityId
from sc2 import unit
from sc2.game_data import AbilityData
from sc2.units import Units
from build_order import Hatch16, Pool12, Pool16

from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO

from common import CommonAI
from utils import CHANGELINGS, armyValue, filterArmy, makeUnique, withEquivalents
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

class ZergAI(CommonAI):

    def __init__(self):
        super(self.__class__, self).__init__()
        # self.buildOrder = random.choice((Pool12, Pool16, Hatch16))()
        self.composition = {}
        self.buildOrder = Hatch16()
        self.goLair = False
        self.goHive = False

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
        self.destroyRocks = 2 <= self.townhalls.ready.amount
        await super(self.__class__, self).on_step(iteration)
        self.micro()
        self.assignWorker()
        await self.microQueens()
        await self.spreadCreepTumor()
        # self.moveOverlord()
        await self.changelingScout()
        self.adjustComposition()

    def getTargets(self) -> List[Union[UnitTypeId, UpgradeId]]:

        if self.buildOrder is not None:
            targets = self.buildOrder.execute(self)
            if targets is None:
                self.buildOrder = None
                return []
            else:
                return targets
        else:
            targets = []
            targets += self.trainQueens()
            targets += self.upgrade()
            targets += self.techUp()
            targets += self.techBuildings()
            targets += self.expandIfNecessary()
            # targets += self.buildSpores()
            targets += self.morphOverlords()
            targets += self.morphUnits()
            self.adjustGasTarget(targets)
            targets += self.buildGasses()
            return targets

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

    def upgrade(self) -> List[UpgradeId]:
        targets = []
        targets.append(UpgradeId.ZERGLINGMOVEMENTSPEED)
        if UnitTypeId.ZERGLING in self.composition:
            if self.goHive:
                targets.append(UpgradeId.ZERGLINGATTACKSPEED)
            targets.extend(self.upgradeSequence(MELEE_UPGRADES))
            targets.extend(self.upgradeSequence(ARMOR_UPGRADES))
        if UnitTypeId.ULTRALISK in self.composition:
            targets.append(UpgradeId.CHITINOUSPLATING)
            targets.append(UpgradeId.ANABOLICSYNTHESIS)
            targets.extend(self.upgradeSequence(MELEE_UPGRADES))
            targets.extend(self.upgradeSequence(ARMOR_UPGRADES))
        if UnitTypeId.BANELING in self.composition:
            targets.append(UpgradeId.CENTRIFICALHOOKS)
            targets.extend(self.upgradeSequence(MELEE_UPGRADES))
            targets.extend(self.upgradeSequence(ARMOR_UPGRADES))
        if UnitTypeId.ROACH in self.composition:
            targets.append(UpgradeId.GLIALRECONSTITUTION)
            targets.extend(self.upgradeSequence(RANGED_UPGRADES))
            targets.extend(self.upgradeSequence(ARMOR_UPGRADES))
        if UnitTypeId.HYDRALISK in self.composition:
            targets.append(UpgradeId.EVOLVEGROOVEDSPINES)
            targets.append(UpgradeId.EVOLVEMUSCULARAUGMENTS)
            targets.extend(self.upgradeSequence(RANGED_UPGRADES))
            targets.extend(self.upgradeSequence(ARMOR_UPGRADES))
        if UnitTypeId.MUTALISK in self.composition:
            targets.extend(self.upgradeSequence(FLYER_UPGRADES))
            targets.extend(self.upgradeSequence(FLYER_ARMOR_UPGRADES))
        if UnitTypeId.CORRUPTOR in self.composition:
            targets.extend(self.upgradeSequence(FLYER_UPGRADES))
            targets.extend(self.upgradeSequence(FLYER_ARMOR_UPGRADES))
        if UnitTypeId.BROODLORD in self.composition:
            targets.extend(self.upgradeSequence(FLYER_ARMOR_UPGRADES))
            targets.extend(self.upgradeSequence(MELEE_UPGRADES))
            targets.extend(self.upgradeSequence(ARMOR_UPGRADES))
        if UnitTypeId.OVERSEER in self.composition:
            targets.append(UpgradeId.OVERLORDSPEED)
        targets = makeUnique(targets)
        targets = [t for t in targets if t not in self.state.upgrades]
        return targets

    def upgradeSequence(self, upgrades) -> List[UpgradeId]:
        for upgrade in upgrades:
            if upgrade not in self.state.upgrades:
                return [upgrade]
        return []

    def techBuildings(self) -> List[UnitTypeId]:
        targets = []
        if UnitTypeId.ZERGLING in self.composition and self.count(UnitTypeId.SPAWNINGPOOL) < 1:
            targets.append(UnitTypeId.SPAWNINGPOOL)
        if (UnitTypeId.ROACH in self.composition or UnitTypeId.RAVAGER in self.composition) and self.count(UnitTypeId.ROACHWARREN) < 1:
            targets.append(UnitTypeId.ROACHWARREN)
        if UnitTypeId.BANELING in self.composition and self.count(UnitTypeId.BANELINGNEST) < 1:
            targets.append(UnitTypeId.BANELINGNEST)
        if (UnitTypeId.HYDRALISK in self.composition or UnitTypeId.LURKER in self.composition) and self.count(UnitTypeId.HYDRALISKDEN) < 1:
            targets.append(UnitTypeId.HYDRALISKDEN)
        if (UnitTypeId.MUTALISK in self.composition or UnitTypeId.CORRUPTOR in self.composition or UnitTypeId.BROODLORD in self.composition) and self.count(UnitTypeId.SPIRE) < 1:
            targets.append(UnitTypeId.SPIRE)
        if UnitTypeId.BROODLORD in self.composition and self.count(UnitTypeId.GREATERSPIRE) < 1:
            targets.append(UnitTypeId.GREATERSPIRE)
        if UnitTypeId.ULTRALISK in self.composition and self.count(UnitTypeId.ULTRALISKCAVERN) < 1:
            targets.append(UnitTypeId.ULTRALISKCAVERN)
        return targets

    async def spreadCreepTumor(self):
        await self.spreadCreep()

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

    def moveOverlord(self, bias=1):
        overlords = self.units(withEquivalents(UnitTypeId.OVERLORD)).idle
        if overlords.exists:
            overlord = overlords.random
            target = random.choice(self.expansion_locations_list)
            overlord.move(target)

    def techUp(self) -> List[UnitTypeId]:
        targets = []
        if self.goLair:
            if self.count(withEquivalents(UnitTypeId.LAIR)) < 1:
                targets.append(UnitTypeId.LAIR)
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
                if self.count(withEquivalents(UnitTypeId.INFESTATIONPIT)) < 1:
                    targets.append(UnitTypeId.INFESTATIONPIT)
                else:
                    targets.append(UnitTypeId.HIVE)
        else:
            self.goHive |= UnitTypeId.ULTRALISK in self.composition
            self.goHive |= UnitTypeId.BROODLORD in self.composition
            self.goHive |= UpgradeId.ZERGMISSILEWEAPONSLEVEL2 in self.state.upgrades
            self.goHive |= UpgradeId.ZERGMELEEWEAPONSLEVEL2 in self.state.upgrades
            self.goHive |= UpgradeId.ZERGGROUNDARMORSLEVEL2 in self.state.upgrades
            self.goHive |= UpgradeId.ZERGFLYERARMORSLEVEL2 in self.state.upgrades
            self.goHive |= UpgradeId.ZERGFLYERARMORSLEVEL2 in self.state.upgrades
        if 2 + self.count(UnitTypeId.EVOLUTIONCHAMBER) < len(self.composition):
            targets.append(UnitTypeId.EVOLUTIONCHAMBER)
        return targets

    async def spreadCreep(self, spreader: Unit = None, numAttempts: int = 3):
        if spreader is None:
            tumors = self.structures(UnitTypeId.CREEPTUMORBURROWED)
            for _ in range(min(tumors.amount, numAttempts)):
                tumor = tumors.random
                if not AbilityId.BUILD_CREEPTUMOR_TUMOR in await self.get_available_abilities(tumor):
                    continue
                spreader = tumor
                break
        if spreader is None:
            return
        if random.random() < 0.5:
            target = spreader.position.towards(random.choice(self.expansion_locations_list), 10)
        else:
            target = spreader.position.towards(self.center, -10)
        if target is None:
            return
        tumorPlacement = None
        for _ in range(numAttempts):
            position = await self.find_placement(AbilityId.ZERGBUILD_CREEPTUMOR, target, placement_step=1)
            if position is None:
                continue
            if self.isBlockingExpansion(position):
                continue
            tumorPlacement = position
            break
        if tumorPlacement is None:
            return
        assert(spreader.build(UnitTypeId.CREEPTUMOR, tumorPlacement))

    def buildSpores(self) -> List[UnitTypeId]:
        sporeTime = {
            Race.Zerg: 8 * 60,
            Race.Protoss: 5 * 60,
            Race.Terran: 5 * 60,
        }
        if (
            sporeTime[self.enemy_race] < self.time
            and self.count(UnitTypeId.SPORECRAWLER) < self.townhalls.amount
            and self.already_pending(UnitTypeId.SPORECRAWLER) < 1
        ):
            return [UnitTypeId.SPORECRAWLER]
        else:
            return[]

    async def microQueens(self):
        queens = self.units(UnitTypeId.QUEEN)
        hatcheries = sorted(self.townhalls, key=lambda h: h.tag)
        queens = sorted(queens, key=lambda q: q.tag)
        assignment = list(zip(hatcheries[:4], queens))
        self.armyBlacklist = { q.tag for _, q in assignment }
        for hatchery, queen in assignment:
            if not queen.is_idle:
                continue
            abilities = await self.get_available_abilities(queen)
            if AbilityId.BUILD_CREEPTUMOR_QUEEN in abilities and 7 < self.larva.amount and random.random() < .3 * math.exp(-.03*self.count(UnitTypeId.CREEPTUMORBURROWED)):
                await self.spreadCreep(spreader=queen)
            elif AbilityId.EFFECT_INJECTLARVA in abilities and hatchery.is_ready:
                queen(AbilityId.EFFECT_INJECTLARVA, hatchery)
            elif 5 < queen.distance_to(hatchery):
                queen.attack(hatchery.position)

    def adjustComposition(self):
        workersTarget = min(80, self.getMaxWorkers())
        self.composition = { UnitTypeId.DRONE: workersTarget }
        # if 3 <= self.townhalls.ready.amount:
        if 4 <= self.townhalls.amount:
            self.composition[UnitTypeId.ROACH] = workersTarget
            self.composition[UnitTypeId.HYDRALISK] = workersTarget
            self.composition[UnitTypeId.OVERSEER] = 1

    def adjustGasTarget(self, targets):
        costs = [self.calculate_cost(t) for t in targets]
        minerals = max(1, sum((c.minerals for c in costs)) - self.minerals)
        vespene = max(1, sum((c.vespene for c in costs)) - self.vespene)
        gasRatio = vespene / (1 + vespene + minerals)
        self.gasTarget = gasRatio * self.workers.amount

    def buildGasses(self) -> List[UnitTypeId]:
        gasActual = self.gas_buildings.filter(lambda v : v.has_vespene).amount
        gasPending = self.already_pending(UnitTypeId.EXTRACTOR)
        gasNeeded = max(0, int(self.gasTarget / 3) - (gasActual + gasPending))
        return gasNeeded * [UnitTypeId.EXTRACTOR]
    
    def trainQueens(self) -> List[UnitTypeId]:
        queenTarget = min(4, self.townhalls.amount)
        queenNeeded = max(0, queenTarget - self.count(UnitTypeId.QUEEN))
        return queenNeeded * [UnitTypeId.QUEEN]

    def morphOverlords(self) -> List[UnitTypeId]:
        if (
            self.supply_cap < 200
            and self.supply_left + self.getSupplyPending() < self.getSupplyBuffer()
        ):
            return [UnitTypeId.OVERLORD]
        else:
            return []

    def expandIfNecessary(self) -> List[UnitTypeId]:

        workerSurplus = sum((h.surplus_harvesters for h in self.townhalls))
        surplusRatio = workerSurplus / self.composition[UnitTypeId.DRONE]
        if self.already_pending(UnitTypeId.HATCHERY) < 1 and -0.2 < surplusRatio:
            return [UnitTypeId.HATCHERY]
        else:
            return []

    def morphUnits(self) -> List[UnitTypeId]:
        targets = []
        for unit, target in self.composition.items():
            missing = target - self.count(unit)
            if missing <= 0:
                continue
            trainer = list(UNIT_TRAINED_FROM[unit])[0]
            if not self.isStructure(trainer) and trainer is not UnitTypeId.LARVA:
                missingTrainers = max(0, missing - self.count(trainer))
                if missingTrainers <= 0:
                    continue
                targets.append(missingTrainers * [trainer])
            targets.append(missing * [unit])
        # random.shuffle(targets)
        targets = sorted(targets, key=lambda t : len(t), reverse=True)
        targets = list(zip(*targets))
        targets = [ti for t in targets for ti in t]
        return targets