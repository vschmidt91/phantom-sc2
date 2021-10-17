
import math
import itertools, random

from s2clientprotocol.error_pb2 import QueueIsFull
from s2clientprotocol.sc2api_pb2 import Macro
from macro_objective import MacroObjective
from s2clientprotocol.raw_pb2 import Unit
from typing import Counter, Iterable, List, Coroutine, Dict, Union

from cost import Cost
from sc2 import AbilityId, game_info
from sc2 import unit
from sc2.dicts.unit_tech_alias import UNIT_TECH_ALIAS
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

from common import SUPPLY, SUPPLY_PROVIDED, UNIT_BY_TRAIN_ABILITY, CommonAI
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

ROACH_RUSH = [
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.SPAWNINGPOOL,
    UnitTypeId.DRONE,
    UnitTypeId.OVERLORD,
    UnitTypeId.EXTRACTOR,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.DRONE,
    UnitTypeId.ROACHWARREN,
    UnitTypeId.QUEEN,
    UnitTypeId.OVERLORD,
    UnitTypeId.ROACH,
    UnitTypeId.ROACH,
    UnitTypeId.ROACH,
    UnitTypeId.ROACH,
    UnitTypeId.ROACH,
    UnitTypeId.ROACH,
    UnitTypeId.ROACH,
    UnitTypeId.ROACH,
    UnitTypeId.ROACH,
    UnitTypeId.ROACH,
    UnitTypeId.ROACH,
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
    UnitTypeId.QUEEN,
    UnitTypeId.QUEEN,
    UpgradeId.ZERGLINGMOVEMENTSPEED,
    UnitTypeId.ZERGLING,
    UnitTypeId.ZERGLING,
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
    UnitTypeId.EXTRACTOR,
    UnitTypeId.QUEEN,
    UnitTypeId.ZERGLING,
    UnitTypeId.ZERGLING,
    UnitTypeId.DRONE,
    UnitTypeId.OVERLORD,
]

CREEP_RANGE = 10
CREEP_ENABLED = True

class ZergAI(CommonAI):

    def __init__(self, **kwargs):
        super(self.__class__, self).__init__(**kwargs)
        self.composition = {}
        self.goLair = False
        self.goHive = False
        self.macroObjectives = [MacroObjective(o, 10) for o in HATCH_FIRST]
        self.gasTarget = 0
        self.timings_acc = {}
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

    async def on_step(self, iteration):

        steps = {
            self.update_tables: 1,
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
            self.trainQueens: 4,
            self.techBuildings: 4,
            self.upgrade: 1,
            self.techUp: 4,
            self.expandIfNecessary: 4,
            # self.buildSpores: 1,
            self.micro: 1,
            self.assignWorker: 1,
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
            # print(self.pending)
            # print(len(self.macroObjectives))
            self.timings_acc = {}

        # if iteration % 100 == 0:
        #     print(sum(self.enemies.values()), sum(unitValue(u) for u in self.units))

        await super().on_step(iteration)

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
            upgrades_want.update(self.upgradeSequence(FLYER_ARMOR_UPGRADES))
            # upgrades_want.update(self.upgradeSequence(MELEE_UPGRADES))
            # upgrades_want.update(self.upgradeSequence(ARMOR_UPGRADES))
        if UnitTypeId.OVERSEER in self.composition:
            upgrades_want.add(UpgradeId.OVERLORDSPEED)

    
        # targets = set(targets)
        # targets = { t for t in targets if not self.already_pending_upgrade(t) }
        # pendingUpgrades = self.state.upgrades | set(t.item for t in self.macroObjectives)
        # pendingUpgrades = { t for t in pendingUpgrades if type(t) is UpgradeId }
        # targets = targets.difference(pendingUpgrades)

        for upgrade in upgrades_want:
            if not self.count(upgrade):
                self.macroObjectives.append(MacroObjective(upgrade))

    def upgradeSequence(self, upgrades) -> Iterable[UpgradeId]:
        for upgrade in upgrades:
            if upgrade not in self.state.upgrades:
                return (upgrade,)
        return tuple()

    def techBuildings(self):

        # if self.buildOrder:
        #     return

        structures_want = set()
        for unit in self.composition:
            trainers = UNIT_TRAINED_FROM[unit]
            for trainer in trainers:
                info = TRAIN_INFO[trainer][unit]

                building = info.get("required_building")
                if building:
                    structures_want.add(building)
                for alias in UNIT_TECH_ALIAS.get(building, set()):
                    structures_want.add(alias)

                # upgrade = info.get("required_upgrade")
                # if upgrade:
                #         continue

        # if UnitTypeId.ZERGLING in self.composition:
        #     structures_want.add(UnitTypeId.SPAWNINGPOOL)
        # if (UnitTypeId.ROACH in self.composition or UnitTypeId.RAVAGER in self.composition):
        #     structures_want.add(UnitTypeId.ROACHWARREN)
        # if UnitTypeId.BANELING in self.composition:
        #     structures_want.add(UnitTypeId.BANELINGNEST)
        # if (UnitTypeId.HYDRALISK in self.composition or UnitTypeId.LURKER in self.composition):
        #     structures_want.add(UnitTypeId.HYDRALISKDEN)
        # if (UnitTypeId.MUTALISK in self.composition or UnitTypeId.CORRUPTOR in self.composition or UnitTypeId.BROODLORD in self.composition):
        #     structures_want.add(UnitTypeId.SPIRE)
        # if UnitTypeId.BROODLORD in self.composition:
        #     structures_want.add(UnitTypeId.GREATERSPIRE)
        # if UnitTypeId.ULTRALISK in self.composition:
        #     structures_want.add(UnitTypeId.ULTRALISKCAVERN)

        for structure in structures_want:
            structure_equivalents = withEquivalents(structure)
            if self.count(structure) or self.count(structure_equivalents, include_planned=False):
                continue
            else:
                self.macroObjectives.append(MacroObjective(structure, 1))
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
        # if self.buildOrder:
        #     return
        if self.townhalls.amount < 4:
            return
        if self.goLair:
            if self.count(UnitTypeId.EVOLUTIONCHAMBER) < 1:
                self.macroObjectives.append(MacroObjective(UnitTypeId.EVOLUTIONCHAMBER, 1))
            if self.count(withEquivalents(UnitTypeId.LAIR)) < 1:
                self.macroObjectives.append(MacroObjective(UnitTypeId.LAIR, 1))
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
            if self.count(UnitTypeId.INFESTATIONPIT) < 1:
                self.macroObjectives.append(MacroObjective(UnitTypeId.INFESTATIONPIT, 1))
            elif self.count(withEquivalents(UnitTypeId.HIVE)) < 1:
                self.macroObjectives.append(MacroObjective(UnitTypeId.HIVE, 1))
            if self.count(UnitTypeId.EVOLUTIONCHAMBER) < 2:
                self.macroObjectives.append(MacroObjective(UnitTypeId.EVOLUTIONCHAMBER, 1))
        else:
            self.goHive |= UnitTypeId.ULTRALISK in self.composition
            self.goHive |= UnitTypeId.BROODLORD in self.composition
            self.goHive |= UpgradeId.ZERGMISSILEWEAPONSLEVEL2 in self.state.upgrades
            self.goHive |= UpgradeId.ZERGMELEEWEAPONSLEVEL2 in self.state.upgrades
            self.goHive |= UpgradeId.ZERGGROUNDARMORSLEVEL2 in self.state.upgrades
            self.goHive |= UpgradeId.ZERGFLYERARMORSLEVEL2 in self.state.upgrades
            self.goHive |= UpgradeId.ZERGFLYERARMORSLEVEL2 in self.state.upgrades

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
            self.macroObjectives.append(MacroObjective(UnitTypeId.SPORECRAWLER))

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

            # abilities = await self.get_available_abilities(queen)
            # if AbilityId.BUILD_CREEPTUMOR_QUEEN in abilities and 7 < self.larva.amount and random.random() < math.exp(-.03*self.count(UnitTypeId.CREEPTUMORBURROWED)):
            #     await self.spreadCreep(spreader=queen)
            # elif AbilityId.EFFECT_INJECTLARVA in abilities and hatchery.is_ready:
            #     queen(AbilityId.EFFECT_INJECTLARVA, hatchery)
            # elif 5 < queen.distance_to(hatchery):
            #     queen.attack(hatchery.position)

    def adjustComposition(self):
        workersTarget = min(72, self.getMaxWorkers())
        self.composition = { UnitTypeId.DRONE: workersTarget }
        if self.townhalls.amount < 3:
            # self.composition[UnitTypeId.ZERGLING] = 8
            pass
        elif self.townhalls.amount < 4:
            # self.composition[UnitTypeId.ZERGLING] = 8
            self.composition[UnitTypeId.ROACH] = 8
            # self.composition[UnitTypeId.ZERGLING] = 50
        else:
            if not self.goLair:
                self.composition[UnitTypeId.ROACH] = 60
                # self.composition[UnitTypeId.ZERGLING] = 50
            elif not self.goHive:
                self.composition[UnitTypeId.OVERSEER] = 1
                self.composition[UnitTypeId.ROACH] = 40
                self.composition[UnitTypeId.HYDRALISK] = 40
                # self.composition[UnitTypeId.HYDRALISK] = 20
                # self.composition[UnitTypeId.ZERGLING] = 40
                # self.composition[UnitTypeId.BANELING] = 40
            else:
                self.composition[UnitTypeId.OVERSEER] = 3
                self.composition[UnitTypeId.CORRUPTOR] = 3
                self.composition[UnitTypeId.BROODLORD] = 10
                self.composition[UnitTypeId.HYDRALISK] = 40
                # self.composition[UnitTypeId.ROACH] = 20
        # else:
        #     self.composition[UnitTypeId.ZERGLING] = 4
        # if 5 <= self.townhalls.amount:
        #     self.composition[UnitTypeId.CORRUPTOR] = workersTarget
        # if 6 <= self.townhalls.amount:
        #     self.composition[UnitTypeId.BROODLORD] = workersTarget

    def adjustGasTarget(self):
        cost_minerals = 0
        cost_vespene = 0

        for objective in self.macroObjectives:
            if objective.cost:
                cost_minerals += objective.cost.minerals
                cost_vespene += objective.cost.vespene

        # for t, n in self.composition.items():
        #     cost = self.calculate_cost(t)
        #     cost_minerals += n * cost.minerals
        #     cost_vespene += n * cost.vespene

        minerals = max(0, cost_minerals - self.minerals)
        vespene = max(0, cost_vespene - self.vespene)
        gasRatio = vespene / max(1, vespene + minerals)
        self.gasTarget = gasRatio * self.count(UnitTypeId.DRONE)
        # self.gasTarget = 3 * int(self.gasTarget / 3)
        # print(self.gasTarget)

    def buildGasses(self):
        # if self.buildOrder:
        #     return
        gas_max = sum(1 for g in self.get_owned_geysers())
        gas_actual = self.gas_buildings.filter(lambda v : v.has_vespene).amount
        gas_pending = self.count_pending(UnitTypeId.EXTRACTOR) + self.count_planned(UnitTypeId.EXTRACTOR)
        gas_have = gas_actual + gas_pending
        gas_want = min(gas_max, int(self.gasTarget / 3))
        gas_need = gas_want - gas_have
        if 0 < gas_need:
            self.macroObjectives.append(MacroObjective(UnitTypeId.EXTRACTOR, 1))
    
    def trainQueens(self):
        # if self.buildOrder:
        #     return
        queenTarget = min(5, 1 + self.townhalls.amount)
        queenPending = sum(1 for o in self.macroObjectives if o.item is UnitTypeId.QUEEN)
        queenTrainer = self.townhalls
        queenTrainer = queenTrainer.filter(lambda t : not t.is_idle)
        queenTrainer = queenTrainer.filter(lambda t : t.orders[0].ability.id is AbilityId.TRAINQUEEN_QUEEN)
        queenPending += queenTrainer.amount
        queenActual = self.units(UnitTypeId.QUEEN).amount
        if queenActual + queenPending < queenTarget:
            self.macroObjectives.append(MacroObjective(UnitTypeId.QUEEN))

    def morphOverlords(self):
        # if self.buildOrder:
        #     return
        if 200 <= self.supply_cap:
            return
        supply_planned = sum(
            SUPPLY_PROVIDED.get(o.item, 0)
            for o in self.macroObjectives
        )
        supply_pending = sum(
            provided * self.count_pending(unit)
            for unit, provided in SUPPLY_PROVIDED.items()
        )
        if 200 <= self.supply_cap + supply_pending + supply_planned:
            return
        if self.supply_left + supply_pending + supply_planned < self.getSupplyBuffer():
            self.macroObjectives.append(MacroObjective(UnitTypeId.OVERLORD, 1))

    def expandIfNecessary(self, max_pending = 1):
        # if self.buildOrder:
        #     return
        saturation_target = 1
        pendingCount = (
            self.count_pending(UnitTypeId.HATCHERY) +
            self.count_planned(UnitTypeId.HATCHERY) +
            self.townhalls.not_ready.amount
        )
        worker_count = self.count(UnitTypeId.DRONE)
        worker_max = self.getMaxWorkers()
        if pendingCount < max_pending and worker_max <= worker_count:
            self.macroObjectives.append(MacroObjective(UnitTypeId.HATCHERY, 0))

    def morphUnits(self):
        

        if self.supply_used == 200:
            return

        # composition_have = {
        #     u: self.count(u)
        #     for u in self.composition.keys()
        # }

        # composition_have[UnitTypeId.DRONE] = self.supply_workers

        composition_missing = [
            MacroObjective(unit, 0 if unit == UnitTypeId.DRONE else -1)
            for unit, n in self.composition.items()
            for i in range(n - self.count(unit))
        ]

        random.shuffle(composition_missing)
        self.macroObjectives.extend(composition_missing)

        # composition_ratio = {
        #     unit: self.count(unit) / max(1, n)
        #     for unit, n in self.composition.items()
        # }

        # for unit, ratio in sorted(composition_ratio.items(), key=lambda p : p[1]):

        #     n = 1

        #     if 3 < self.count_planned(unit):
        #         continue

        #     if 1 <= ratio:
        #         continue

        #     self.macroObjectives.extend((MacroObjective(unit, -1) for i in range(n)))

        #     trainer = sorted(UNIT_TRAINED_FROM[unit], key=lambda v:v.value)[0]
        #     if not self.isStructure(trainer) and trainer is not UnitTypeId.LARVA:
        #         self.macroObjectives.extend((MacroObjective(trainer, -1) for i in range(n)))