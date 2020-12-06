
import itertools, random

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

    async def on_unit_created(self, unit: unit):
        if unit.type_id is UnitTypeId.OVERLORD and  self.structures(withEquivalents(UnitTypeId.LAIR)).exists:
                unit(AbilityId.BEHAVIOR_GENERATECREEPON)

    async def on_before_start(self):

        # await self.client.debug_show_map()

        self.destroyRocks = False
        self.enemies = { u: 0 for u in UNIT_COUNTERS[UnitTypeId.ZERGLING].keys() }
        self.buildOrder = random.choice((Pool12(), Pool16(), Hatch16()))
        self.goLair = False
        self.goHive = False
        await super(self.__class__, self).on_before_start()

    async def on_step(self, iteration: int):
        await self.microQueens()
        await self.spreadCreep()
        # self.moveOverlord()
        await self.changelingScout()
        await super(self.__class__, self).on_step(iteration)

    def counterComposition(self, enemies: Units):

        enemyValue = sum((self.unitValue(u) * n for u, n in enemies.items()))
        weights = {
            u: sum((w * self.unitValue(v) * enemies[v] for v, w in vw.items()))
            for u, vw in UNIT_COUNTERS.items()
        }

        techTargets = []
        composition = {}

        weights = sorted(weights.items(), key=lambda p: p[1], reverse=True)

        for u, w in weights:
            if self.tech_requirement_progress(u) == 0 or (u is UnitTypeId.ULTRALISK and not self.structures(UnitTypeId.ULTRALISKCAVERN).exists):
                if len(techTargets) < 1:
                    techTargets.append(u)
                continue
            elif w < 0 and 0 < len(composition):
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

    def upgrade(self):

        unitUpgrades = []
        evoUpgrades = []

        if 16 <= self.composition.get(UnitTypeId.ZERGLING, 0):
            unitUpgrades += [UpgradeId.ZERGLINGMOVEMENTSPEED, UpgradeId.ZERGLINGATTACKSPEED]
            evoUpgrades += MELEE_UPGRADES

        if UnitTypeId.ULTRALISK in self.composition:
            unitUpgrades.append(UpgradeId.CHITINOUSPLATING)
            evoUpgrades += MELEE_UPGRADES
            self.goHive = True

        if UnitTypeId.BANELING in self.composition:
            unitUpgrades.append(UpgradeId.CENTRIFICALHOOKS)
            evoUpgrades += MELEE_UPGRADES
            self.goLair = True

        if UnitTypeId.ROACH in self.composition:
            unitUpgrades.append(UpgradeId.GLIALRECONSTITUTION)
            evoUpgrades += RANGED_UPGRADES
            self.goLair = True

        if UnitTypeId.HYDRALISK in self.composition:
            unitUpgrades += [UpgradeId.EVOLVEGROOVEDSPINES, UpgradeId.EVOLVEMUSCULARAUGMENTS]
            evoUpgrades += RANGED_UPGRADES
            self.goLair = True

        if UnitTypeId.MUTALISK in self.composition:
            unitUpgrades += FLYER_UPGRADES
            self.goLair = True

        if UnitTypeId.CORRUPTOR in self.composition:
            unitUpgrades += FLYER_UPGRADES
            self.goLair = True

        if UnitTypeId.BROODLORD in self.composition:
            # unitUpgrades += FLYER_UPGRADES
            # evoTargets += MELEE_UPGRADES
            self.goHive = True
            pass

        if 4 <= self.townhalls.amount:
            unitUpgrades.append(UpgradeId.OVERLORDSPEED)

        upgrades = [
            u for u in unitUpgrades + makeUnique(evoUpgrades)
            if (
                not u in self.state.upgrades
                and self.tech_requirement_progress(u) == 1
                and not self.already_pending_upgrade(u)
            )
        ]

        return list(upgrades)

    def techBuildings(self, techTargets):

        targets = []

        if self.count(UnitTypeId.ROACHWARREN) < 1 and UnitTypeId.ROACH in techTargets:
            targets += [UnitTypeId.ROACHWARREN]
        if self.count(UnitTypeId.BANELINGNEST) < 1 and UnitTypeId.BANELING in techTargets:
            targets += [UnitTypeId.BANELINGNEST]
        if self.count(UnitTypeId.HYDRALISKDEN) < 1 and UnitTypeId.HYDRALISK in techTargets:
            targets += [UnitTypeId.HYDRALISKDEN]
        if self.count(withEquivalents(UnitTypeId.SPIRE)) < 1 and UnitTypeId.MUTALISK in techTargets:
            targets += [UnitTypeId.SPIRE]
        if self.count(withEquivalents(UnitTypeId.SPIRE)) < 1 and UnitTypeId.CORRUPTOR in techTargets:
            targets += [UnitTypeId.SPIRE]
        if self.count(withEquivalents(UnitTypeId.SPIRE)) < 1 and UnitTypeId.BROODLORD in techTargets:
            targets += [UnitTypeId.SPIRE]
        if self.count(UnitTypeId.GREATERSPIRE) < 1 and UnitTypeId.BROODLORD in techTargets:
            targets += [UnitTypeId.GREATERSPIRE]
        if self.count(UnitTypeId.ULTRALISKCAVERN) < 1 and UnitTypeId.ULTRALISK in techTargets:
            targets += [UnitTypeId.ULTRALISKCAVERN]

        return targets

    def techUp(self, techTargets):

        targets = []

        self.goHive |= UnitTypeId.ULTRALISK in techTargets
        self.goHive |= UnitTypeId.BROODLORD in techTargets

        self.goLair |= UnitTypeId.BANELING in techTargets
        self.goLair |= UnitTypeId.ROACH in techTargets
        self.goLair |= UnitTypeId.HYDRALISK in techTargets
        self.goLair |= UnitTypeId.MUTALISK in techTargets
        self.goLair |= UnitTypeId.CORRUPTOR in techTargets

        self.goLair |= UpgradeId.ZERGMISSILEWEAPONSLEVEL1 in self.state.upgrades
        self.goLair |= UpgradeId.ZERGMELEEWEAPONSLEVEL1 in self.state.upgrades
        self.goLair |= UpgradeId.ZERGGROUNDARMORSLEVEL1 in self.state.upgrades

        self.goHive |= UpgradeId.ZERGMISSILEWEAPONSLEVEL2 in self.state.upgrades
        self.goHive |= UpgradeId.ZERGMELEEWEAPONSLEVEL2 in self.state.upgrades
        self.goHive |= UpgradeId.ZERGGROUNDARMORSLEVEL2 in self.state.upgrades
        self.goHive |= UpgradeId.ZERGFLYERARMORSLEVEL2 in self.state.upgrades
        self.goHive |= UpgradeId.ZERGFLYERARMORSLEVEL2 in self.state.upgrades

        self.goLair |= self.goHive

        if 33 * (1 + self.count(UnitTypeId.EVOLUTIONCHAMBER)) < self.workers.amount:
            targets.append(UnitTypeId.EVOLUTIONCHAMBER)

        if self.goLair:
            if self.count(withEquivalents(UnitTypeId.LAIR)) < 1:
                targets.append(UnitTypeId.LAIR)
        if self.goHive:
            if self.count(withEquivalents(UnitTypeId.INFESTATIONPIT)) < 1:
                targets.append(UnitTypeId.INFESTATIONPIT)
            elif self.count(withEquivalents(UnitTypeId.HIVE)) < 1:
                targets.append(UnitTypeId.HIVE)

        return targets

    def buildSpores(self):

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

        return []

    def getTargets(self):

        if self.buildOrder is not None:
            buildOrderTargets = self.buildOrder.getTargets(self)
            if buildOrderTargets is None:
                self.buildOrder = None
            else:
                return buildOrderTargets

        workersMax = self.getMaxWorkers()
        workersTarget = min(60 , workersMax)
        
        self.enemies = { u: max(.999 * v, self.enemy_units(u).amount) for u, v in self.enemies.items() }

        counterComposition, techTargets = self.counterComposition(self.enemies)

        self.composition = {
            **counterComposition,
            UnitTypeId.DRONE: workersTarget,
            UnitTypeId.OVERSEER: 1,
        }

        self.composition[UnitTypeId.ZERGLING] = max(4, self.composition.get(UnitTypeId.ZERGLING, 0))
        # self.composition[UnitTypeId.QUEEN] = min(4, self.townhalls.amount) + self.composition.get(UnitTypeId.QUEEN, 0)
        
        compositionCounts = { u: self.count(u) for u in self.composition.keys() }
        compositionMissing = { u: max(0, n - compositionCounts[u]) for u, n in self.composition.items() }
        
        compositionCost = { u: self.calculate_cost(u) for u in self.composition.keys() }
        compositionGas = sum((compositionMissing[u] * compositionCost[u].vespene for u in self.composition.keys()))
        compositionGas = max(0, compositionGas - self.vespene)
        compositionMinerals = sum((compositionMissing[u] * compositionCost[u].minerals for u in self.composition.keys()))
        compositionMinerals = max(0, compositionMinerals - self.minerals)
        gasRatio = (1 + compositionGas) / (2 + compositionGas + compositionMinerals)

        if self.goLair:
            gasRatio = max(.1, gasRatio)

        if self.goHive:
            gasRatio = max(.2, gasRatio)

        self.gasTarget = gasRatio * self.workers.amount


        targets = []

        gasActual = self.gas_buildings.filter(lambda v : v.has_vespene).amount
        gasPending = self.already_pending(UnitTypeId.EXTRACTOR)
        gasCount = gasActual + gasPending
        gasMax = sum((sum((1 for g in self.expansion_locations_dict[b] if g.is_vespene_geyser)) for b in self.owned_expansions.keys()))

        targets += itertools.repeat(UnitTypeId.EXTRACTOR, max(0, min(gasMax, int(self.gasTarget / 3)) - gasCount))

        targets += itertools.repeat(UnitTypeId.OVERLORD, max(0, self.getSupplyTarget() - self.count(UnitTypeId.OVERLORD)))
        
        queenTarget = min(4, self.townhalls.amount)
        targets += itertools.repeat(UnitTypeId.QUEEN, max(0, queenTarget - self.count(UnitTypeId.QUEEN)))
    
        if .333 < self.advantage:
            targets += self.buildSpores()
            targets += self.techBuildings(techTargets[0:1])
        if .666 < self.advantage:
            targets += self.upgrade()
            targets += self.techUp(techTargets)


        if self.already_pending(UnitTypeId.HATCHERY) < 1 and -8 < sum((h.surplus_harvesters for h in self.townhalls)):
            targets.append(UnitTypeId.HATCHERY)

        compositionTargets = { u: compositionCounts[u] / n for u, n in self.composition.items() if 0 < n }

        # if all((.5 < w for w in compositionTargets.values())):
        #     if not self.goLair:
        #         self.goLair = True
            # elif not self.goHive:
            #     self.goHive = True

        unitTargets = []
        for u, w in sorted(compositionTargets.items(), key=lambda p: p[1]):
            t = list(UNIT_TRAINED_FROM[u])[0]
            if t in UNIT_COUNTERS.keys() and self.count(t) < max(1, compositionMissing[u]):
                unitTargets.append(t)
            else:
                unitTargets.append(u)

        self.advantage = sum((compositionCounts[u] * self.unitValue(u) for u in self.composition.keys())) / sum((self.composition[u] * self.unitValue(u) for u in self.composition.keys()))

        targets += unitTargets

        if 50 < self.supply_used and self.already_pending(UnitTypeId.OVERLORD) < 1:
            targets.append(UnitTypeId.OVERLORD)

        return targets