
import itertools, random
from s2clientprotocol.raw_pb2 import Unit

from sc2 import AbilityId
from sc2 import unit
from sc2.game_data import AbilityData
from sc2.units import Units
from build_order import Hatch16, Pool12, Pool16

from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM

from common import CommonAI
from utils import armyValue, filterArmy, makeUnique, withEquivalents
from unit_counters import UNIT_COUNTERS

MELEE_UPGRADES = [
    UpgradeId.ZERGMELEEWEAPONSLEVEL1,
    UpgradeId.ZERGMELEEWEAPONSLEVEL2,
    UpgradeId.ZERGMELEEWEAPONSLEVEL3,
    UpgradeId.ZERGGROUNDARMORSLEVEL1,
    UpgradeId.ZERGGROUNDARMORSLEVEL2,
    UpgradeId.ZERGGROUNDARMORSLEVEL3,
]

RANGED_UPGRADES = [
    UpgradeId.ZERGMISSILEWEAPONSLEVEL1,
    UpgradeId.ZERGMISSILEWEAPONSLEVEL2,
    UpgradeId.ZERGMISSILEWEAPONSLEVEL3,
    UpgradeId.ZERGGROUNDARMORSLEVEL1,
    UpgradeId.ZERGGROUNDARMORSLEVEL2,
    UpgradeId.ZERGGROUNDARMORSLEVEL3,
]

FLYER_UPGRADES = [
    UpgradeId.ZERGFLYERWEAPONSLEVEL1,
    UpgradeId.ZERGFLYERWEAPONSLEVEL2,
    UpgradeId.ZERGFLYERWEAPONSLEVEL3,
    UpgradeId.ZERGFLYERARMORSLEVEL1,
    UpgradeId.ZERGFLYERARMORSLEVEL2,
    UpgradeId.ZERGFLYERARMORSLEVEL3,
]

class ZergAI(CommonAI):

    def __init__(self):
        super(self.__class__, self).__init__()
        self.enemies = { u: 0 for u in UNIT_COUNTERS[UnitTypeId.ROACH].keys() }
        # self.buildOrder = random.choice((Pool12, Pool16, Hatch16))()
        self.buildOrder = Hatch16()
        self.goLair = False
        self.goHive = False

    def getChain(self):
        if self.buildOrder is None:
            return [
                self.micro,
                self.assignWorker,
                self.microQueens,
                self.spreadCreepTumor,
                # self.moveOverlord,
                self.changelingScout,
                self.adjustComposition,
                self.adjustGasTarget,
                self.upgrade,
                self.techUp,
                self.techBuildings,
                self.expandIfNecessary,
                # self.buildSpores,
                self.trainQueens,
                self.buildGasses,
                self.morphOverlords,
                self.morphUnits,
            ]
        else:
            return [
                self.micro,
                self.executeBuildOrder,
            ]

    async def on_unit_created(self, unit):
        if unit.type_id is UnitTypeId.OVERLORD and  self.structures(withEquivalents(UnitTypeId.LAIR)).exists:
            unit(AbilityId.BEHAVIOR_GENERATECREEPON)

    async def on_before_start(self):
        await super(self.__class__, self).on_before_start()
        # await self.client.debug_show_map()

    async def on_step(self, iteration):
        await super(self.__class__, self).on_step(iteration)
        self.destroyRocks = 2 <= self.townhalls.ready.amount

    def counterComposition(self, enemies):

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
            u: (w  / weightSum) * (enemyValue / self.unitValue(u))
            for u, w in composition.items()
        }

        # if 2 <= len(composition):
        #     techTargets = []

        return composition, techTargets

    async def upgrade(self, reserve):

        upgrades = []

        if UnitTypeId.ZERGLING in self.composition:
            upgrades.append(UpgradeId.ZERGLINGMOVEMENTSPEED)
            upgrades.append(UpgradeId.ZERGLINGATTACKSPEED)
            upgrades.extend(MELEE_UPGRADES)

        if UnitTypeId.ULTRALISK in self.composition:
            upgrades.append(UpgradeId.CHITINOUSPLATING)
            upgrades.append(UpgradeId.ANABOLICSYNTHESIS)
            upgrades.extend(MELEE_UPGRADES)

        if UnitTypeId.BANELING in self.composition:
            upgrades.append(UpgradeId.CENTRIFICALHOOKS)
            upgrades.extend(MELEE_UPGRADES)

        if UnitTypeId.ROACH in self.composition:
            upgrades.append(UpgradeId.GLIALRECONSTITUTION)
            upgrades.extend(RANGED_UPGRADES)

        if UnitTypeId.HYDRALISK in self.composition:
            upgrades += [UpgradeId.EVOLVEGROOVEDSPINES, UpgradeId.EVOLVEMUSCULARAUGMENTS]
            upgrades.extend(RANGED_UPGRADES)

        if UnitTypeId.MUTALISK in self.composition:
            upgrades.extend(FLYER_UPGRADES)

        if UnitTypeId.CORRUPTOR in self.composition:
            upgrades.extend(FLYER_UPGRADES)

        # if UnitTypeId.BROODLORD in self.composition:
        #     upgrades.extend(FLYER_UPGRADES)
        #     upgrades.extend(MELEE_UPGRADES)

        if 4 <= self.townhalls.amount:
            upgrades.append(UpgradeId.OVERLORDSPEED)

        upgradesUnique = makeUnique(upgrades)
        upgradesUnique = sorted(upgradesUnique, key=lambda u : upgrades.count(u), reverse=True)

        for upgrade in upgradesUnique:
            reserve = await self.research(upgrade, reserve)

        return reserve

    async def techBuildings(self, reserve):

        if (UnitTypeId.ROACH in self.techTargets or UnitTypeId.RAVAGER in self.techTargets) and self.count(UnitTypeId.ROACHWARREN) < 1:
            reserve = await self.train(UnitTypeId.ROACHWARREN, reserve)
        if UnitTypeId.BANELING in self.techTargets and self.count(UnitTypeId.BANELINGNEST) < 1:
            reserve = await self.train(UnitTypeId.BANELINGNEST, reserve)
        if (UnitTypeId.HYDRALISK in self.techTargets or UnitTypeId.LURKER in self.techTargets) and self.count(UnitTypeId.HYDRALISKDEN) < 1:
            reserve = await self.train(UnitTypeId.HYDRALISKDEN, reserve)
        if (UnitTypeId.MUTALISK in self.techTargets or UnitTypeId.CORRUPTOR in self.techTargets or UnitTypeId.BROODLORD in self.techTargets) and self.count(UnitTypeId.SPIRE) < 1:
            reserve = await self.train(UnitTypeId.SPIRE, reserve)
        if UnitTypeId.BROODLORD in self.techTargets and self.count(UnitTypeId.GREATERSPIRE) < 1:
            reserve = await self.train(UnitTypeId.GREATERSPIRE, reserve)
        if UnitTypeId.ULTRALISK in self.techTargets and self.count(UnitTypeId.ULTRALISKCAVERN) < 1:
            reserve = await self.train(UnitTypeId.ULTRALISKCAVERN, reserve)

        return reserve

    async def spreadCreepTumor(self):
        await self.spreadCreep()

    async def techUp(self, reserve):

        if not self.goLair:

            self.goLair |= UnitTypeId.BANELING in self.techTargets
            self.goLair |= UnitTypeId.ROACH in self.techTargets
            self.goLair |= UnitTypeId.HYDRALISK in self.techTargets
            self.goLair |= UnitTypeId.MUTALISK in self.techTargets
            self.goLair |= UnitTypeId.CORRUPTOR in self.techTargets

            self.goLair |= UpgradeId.ZERGMISSILEWEAPONSLEVEL1 in self.state.upgrades
            self.goLair |= UpgradeId.ZERGMELEEWEAPONSLEVEL1 in self.state.upgrades
            self.goLair |= UpgradeId.ZERGGROUNDARMORSLEVEL1 in self.state.upgrades

            self.goLair |= self.goHive

        if not self.goHive:

            self.goHive |= UnitTypeId.ULTRALISK in self.techTargets
            self.goHive |= UnitTypeId.BROODLORD in self.techTargets

            self.goHive |= UpgradeId.ZERGMISSILEWEAPONSLEVEL2 in self.state.upgrades
            self.goHive |= UpgradeId.ZERGMELEEWEAPONSLEVEL2 in self.state.upgrades
            self.goHive |= UpgradeId.ZERGGROUNDARMORSLEVEL2 in self.state.upgrades
            self.goHive |= UpgradeId.ZERGFLYERARMORSLEVEL2 in self.state.upgrades
            self.goHive |= UpgradeId.ZERGFLYERARMORSLEVEL2 in self.state.upgrades

        if 30 * (1 + self.count(UnitTypeId.EVOLUTIONCHAMBER)) < self.workers.amount:
            reserve = await self.train(UnitTypeId.EVOLUTIONCHAMBER, reserve)

        if self.goLair:
            if self.count(withEquivalents(UnitTypeId.LAIR)) < 1:
                reserve = await self.train(UnitTypeId.LAIR, reserve)
        if self.goHive:
            if self.count(withEquivalents(UnitTypeId.INFESTATIONPIT)) < 1:
                reserve = await self.train(UnitTypeId.INFESTATIONPIT, reserve)
            elif self.count(withEquivalents(UnitTypeId.HIVE)) < 1:
                reserve = await self.train(UnitTypeId.HIVE, reserve)

        return reserve

    async def buildSpores(self, reserve):

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
            reserve = await self.train(UnitTypeId.SPORECRAWLER, reserve)

        return reserve

    def adjustComposition(self):
        
        self.enemies = { u: max(.999 * v, self.enemy_units(u).amount) for u, v in self.enemies.items() }

        counterComposition, techTargets = self.counterComposition(self.enemies)
        self.techTargets = techTargets[0:1]

        # counterComposition = {}
        # techTargets = []

        # if self.townhalls.amount < 3:
        #     pass
        # elif 0 < self.getTechDistance(UnitTypeId.ROACH):
        #     techTargets.append(UnitTypeId.ROACH)
        # else:
        #     counterComposition[UnitTypeId.ROACH] = 30

        # if self.townhalls.amount < 4:
        #     pass
        # elif 0 < self.getTechDistance(UnitTypeId.HYDRALISK):
        #     techTargets.append(UnitTypeId.HYDRALISK)
        # else:
        #     counterComposition[UnitTypeId.HYDRALISK] = 30

        workersTarget = min(70, self.getMaxWorkers())

        self.composition = {
            UnitTypeId.DRONE: workersTarget,
            UnitTypeId.ZERGLING: 1,
            UnitTypeId.OVERSEER: 1,
            **counterComposition,
        }

        self.compositionCounts = { u: self.count(u) for u in self.composition.keys() }
        self.compositionMissing = { u: max(0, n - self.compositionCounts[u]) for u, n in self.composition.items() }
        self.compositionTargets = { u: self.compositionCounts[u] / n for u, n in self.composition.items() if 0 < n }

        self.advantage = sum((self.compositionCounts[u] * self.unitValue(u) for u in self.composition.keys())) / sum((self.composition[u] * self.unitValue(u) for u in self.composition.keys()))

    def adjustGasTarget(self):

        compositionCost = { u: self.calculate_cost(u) for u in self.composition.keys() }
        compositionGas = sum((self.compositionMissing[u] * compositionCost[u].vespene for u in self.composition.keys()))
        compositionGas = max(1, compositionGas - self.vespene)
        compositionMinerals = sum((self.compositionMissing[u] * compositionCost[u].minerals for u in self.composition.keys()))
        compositionMinerals = max(2, compositionMinerals - self.minerals)
        gasRatio = compositionGas / (compositionGas + compositionMinerals)

        self.gasTarget = gasRatio * self.workers.amount
        self.gasTarget += 3

    async def executeBuildOrder(self, reserve):

        if self.buildOrder is not None:
            reserve = await self.buildOrder.execute(self, reserve)
            
        return reserve

    async def buildGasses(self, reserve):

        gasActual = self.gas_buildings.filter(lambda v : v.has_vespene).amount
        gasPending = self.already_pending(UnitTypeId.EXTRACTOR)
        if gasActual + gasPending < int(self.gasTarget / 3):
            reserve = await self.train(UnitTypeId.EXTRACTOR, reserve)

        return reserve
    
    async def trainQueens(self, reserve):
        
        queenTarget = min(4, self.townhalls.amount)
        queenNeeded = max(0, queenTarget - self.count(UnitTypeId.QUEEN))

        for _ in range(queenNeeded):
            reserve = await self.train(UnitTypeId.QUEEN, reserve)

        return reserve

    async def morphOverlords(self, reserve):

        if (
            self.supply_cap < 200
            and self.supply_left + self.getSupplyPending() < self.getSupplyBuffer()
        ):
            reserve = await self.train(UnitTypeId.OVERLORD, reserve)

        return reserve

    async def expandIfNecessary(self, reserve):

        workerSurplus = sum((h.surplus_harvesters for h in self.townhalls))
        if self.already_pending(UnitTypeId.HATCHERY) < 1 and -8 < workerSurplus:
            reserve = await self.train(UnitTypeId.HATCHERY, reserve)

        return reserve

    async def morphUnits(self, reserve):

        for u, w in sorted(self.compositionTargets.items(), key=lambda p: p[1]):
            if u is UnitTypeId.DRONE:
                if 1 <= w:
                    continue
            else:
                if 2 <= w:
                    continue
            t = list(UNIT_TRAINED_FROM[u])[0]
            if t in UNIT_COUNTERS.keys() and self.count(t) < max(1, self.compositionMissing[u]):
                reserve = await self.train(t, reserve)
            else:
                reserve = await self.train(u, reserve)

        return reserve