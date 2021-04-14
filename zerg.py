
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
        self.composition = {}
        self.compositionTargets = {}
        self.techTargets = []
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
        self.adjustGasTarget()
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
            targets += self.buildGasses()
            targets += self.morphOverlords()
            targets += self.morphUnits()
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
            upgrades.append(UpgradeId.EVOLVEGROOVEDSPINES)
            upgrades.append(UpgradeId.EVOLVEMUSCULARAUGMENTS)
            upgrades.extend(RANGED_UPGRADES)

        if UnitTypeId.MUTALISK in self.composition:
            upgrades.extend(FLYER_UPGRADES)

        if UnitTypeId.CORRUPTOR in self.composition:
            upgrades.extend(FLYER_UPGRADES)

        if UnitTypeId.BROODLORD in self.composition:
            upgrades.append(UpgradeId.ZERGFLYERARMORSLEVEL1)
            upgrades.append(UpgradeId.ZERGFLYERARMORSLEVEL2)
            upgrades.append(UpgradeId.ZERGFLYERARMORSLEVEL3)
            upgrades.extend(MELEE_UPGRADES)

        # upgrades.append(UpgradeId.OVERLORDSPEED)

        upgrades = makeUnique(upgrades)
        upgrades = [
            u for u in upgrades
            if self.tech_requirement_progress(u) == 1
        ]

        return upgrades

    def techBuildings(self) -> List[UnitTypeId]:

        structures = []

        if (UnitTypeId.ROACH in self.techTargets or UnitTypeId.RAVAGER in self.techTargets) and self.count(UnitTypeId.ROACHWARREN) < 1:
            structures.append(UnitTypeId.ROACHWARREN)
        if UnitTypeId.BANELING in self.techTargets and self.count(UnitTypeId.BANELINGNEST) < 1:
            structures.append(UnitTypeId.BANELINGNEST)
        if (UnitTypeId.HYDRALISK in self.techTargets or UnitTypeId.LURKER in self.techTargets) and self.count(UnitTypeId.HYDRALISKDEN) < 1:
            structures.append(UnitTypeId.HYDRALISKDEN)
        if (UnitTypeId.MUTALISK in self.techTargets or UnitTypeId.CORRUPTOR in self.techTargets or UnitTypeId.BROODLORD in self.techTargets) and self.count(UnitTypeId.SPIRE) < 1:
            structures.append(UnitTypeId.SPIRE)
        if UnitTypeId.BROODLORD in self.techTargets and self.count(UnitTypeId.GREATERSPIRE) < 1:
            structures.append(UnitTypeId.GREATERSPIRE)
        if UnitTypeId.ULTRALISK in self.techTargets and self.count(UnitTypeId.ULTRALISKCAVERN) < 1:
            structures.append(UnitTypeId.ULTRALISKCAVERN)

        return structures

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

        structures = []
        if 30 * (1 + self.count(UnitTypeId.EVOLUTIONCHAMBER)) < self.workers.amount:
            structures.append(UnitTypeId.EVOLUTIONCHAMBER)

        if self.goLair:
            if self.count(withEquivalents(UnitTypeId.LAIR)) < 1:
                structures.append(UnitTypeId.LAIR)
        if self.goHive:
            if self.count(withEquivalents(UnitTypeId.INFESTATIONPIT)) < 1:
                structures.append(UnitTypeId.INFESTATIONPIT)
            elif self.count(withEquivalents(UnitTypeId.HIVE)) < 1:
                structures.append(UnitTypeId.HIVE)

        return structures

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
        
        self.enemies = { u: max(.999 * v, self.enemy_units(u).amount) for u, v in self.enemies.items() }

        counterComposition, techTargets = self.counterComposition(self.enemies)
        if 2 < self.townhalls.amount:
            self.techTargets = [UnitTypeId.ROACH]
        if 3 < self.townhalls.amount:
            self.techTargets = [UnitTypeId.HYDRALISK, UnitTypeId.ROACH]
        # self.techTargets = techTargets[0:1]

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

        if self.townhalls.amount < 4:
            self.composition = {
                UnitTypeId.DRONE: workersTarget,
            }
        else:
            self.composition = {
                UnitTypeId.DRONE: workersTarget,
                UnitTypeId.HYDRALISK: workersTarget,
                UnitTypeId.ROACH: workersTarget,
                UnitTypeId.OVERSEER: 1,
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
        # self.gasTarget += 3

    async def executeBuildOrder(self, reserve):

        if self.buildOrder is not None:
            reserve = await self.buildOrder.execute(self, reserve)
            
        return reserve

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
        if self.already_pending(UnitTypeId.HATCHERY) < 1 and -8 < workerSurplus:
            return [UnitTypeId.HATCHERY]
        else:
            return []

    def morphUnits(self) -> List[UnitTypeId]:
        units = []
        for u, n in sorted(self.compositionMissing.items(), key=lambda p: p[1], reverse=True):
            t = list(UNIT_TRAINED_FROM[u])[0]
            if t in UNIT_COUNTERS.keys() and self.count(t) < n:
                w2 = max(0, n - self.count(t))
                units.extend(w2 * [t])
            units.extend(n * [u])
        # for u, w in sorted(self.compositionTargets.items(), key=lambda p: p[1]):
        #     if u is UnitTypeId.DRONE:
        #         if 1 <= w:
        #             continue
        #     else:
        #         if 2 <= w:
        #             continue
        #     t = list(UNIT_TRAINED_FROM[u])[0]
        #     if t in UNIT_COUNTERS.keys() and self.count(t) < max(1, self.compositionMissing[u]):
        #         units.append(t)
        #     else:
        #         units.append(u)
        random.shuffle(units)
        return units