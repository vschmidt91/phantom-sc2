
import inspect
import itertools

import math
import random

from sc2.game_data import Cost
from utils import CHANGELINGS, armyValue, canAttack, center, dot, filterArmy, withEquivalents

import numpy as np
from sc2.position import Point2

from sc2 import Race, BotAI
from sc2.constants import ALL_GAS
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.ids.upgrade_id import UpgradeId
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.constants import EQUIVALENTS_FOR_TECH_PROGRESS
from sc2.constants import IS_STRUCTURE
from sc2.data import Alliance, Result, race_townhalls, race_worker
from sc2.dicts.unit_research_abilities import RESEARCH_INFO
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.dicts.unit_tech_alias import UNIT_TECH_ALIAS
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2

from reserve import Reserve

PHI = .5 * (1 + math.sqrt(5))

SUPPLY = {
    Race.Protoss: UnitTypeId.PYLON,
    Race.Terran: UnitTypeId.SUPPLYDEPOT,
    Race.Zerg: UnitTypeId.OVERLORD,
}

TOWNHALL = {
    Race.Protoss: UnitTypeId.NEXUS,
    Race.Terran: UnitTypeId.COMMANDCENTER,
    Race.Zerg: UnitTypeId.HATCHERY,
}

STATIC_DEFENSE = {
    Race.Protoss: { UnitTypeId.PHOTONCANNON },
    Race.Terran: { UnitTypeId.MISSILETURRET },
    Race.Zerg: { UnitTypeId.SPINECRAWLER, UnitTypeId.SPORECRAWLER },
}

class CommonAI(BotAI):

    def __init__(self):
        self.raw_affects_selection = True
        self.destroyRocks = False
        self.iteration = 0
        self.gasTarget = 0
        self.advantage = 0
        self.injectQueens = []

    def micro(self):

        CIVILIANS = { UnitTypeId.SCV, UnitTypeId.MULE, UnitTypeId.PROBE }
        CIVILIANS |= withEquivalents(UnitTypeId.DRONE)
        # CIVILIANS |= withEquivalents(UnitTypeId.QUEEN)
        CIVILIANS |= withEquivalents(UnitTypeId.OVERLORD)
        CIVILIANS |= withEquivalents(UnitTypeId.BROODLING)
        # CIVILIANS |= withEquivalents(UnitTypeId.OVERSEER)
        CIVILIANS |= withEquivalents(UnitTypeId.OBSERVER)
        CIVILIANS |= { UnitTypeId.LARVA, UnitTypeId.EGG }
        CIVILIANS |= CHANGELINGS

        army = self.units.exclude_type(CIVILIANS)
        army = army.tags_not_in(self.injectQueens)

        if not army.exists:
            return
        arymCenter = center(army)

        retreatPoint = self.center + .5 * self.advantage * (arymCenter - self.center)

        enemyArmy = self.enemy_units | self.enemy_structures
        # for d in STATIC_DEFENSE.values():
        #     enemyArmy += self.enemy_structures(d)
        enemyArmy = enemyArmy.filter(lambda e : not e.is_gathering)
        enemyArmy = enemyArmy.filter(lambda e : not e.is_carrying_resource)
        enemyArmy = enemyArmy.filter(lambda e : not e.is_hallucination)
        enemyArmy = enemyArmy.exclude_type(withEquivalents(UnitTypeId.OVERLORD))
        enemyArmy = enemyArmy.exclude_type(withEquivalents(UnitTypeId.OVERSEER))
        enemyArmy = enemyArmy.exclude_type(withEquivalents(UnitTypeId.OBSERVER))

        # rocks = self.all_units.filter(lambda r: "Destructible" in r.name)
        # rocks = rocks.filter(lambda r: r.distance_to(self.center) < 2 * r.distance_to(self.enemyCenter))

        neutrals = self.enemy_units(CIVILIANS)
        rocks = self.all_units.filter(lambda r: "Destructible" in r.name)
        rocks = rocks.filter(lambda r: r.distance_to(self.center) < 2 * r.distance_to(self.enemyCenter))

        if self.destroyRocks:
            neutrals |= rocks

        if self.iteration % 32 == 0:
            print(self.advantage)

        if enemyArmy.exists:

            for unit in army:

                # if self.iteration % 8 != unit.tag % 8:
                #     continue

                enemy = enemyArmy.closest_to(unit)

                enemies = enemyArmy.filter(lambda e : canAttack(e, unit))
                friends = army.filter(lambda f : canAttack(f, enemy))

                # enemies = enemyArmy
                # friends = army

                biasValue = 1
                enemyValue = biasValue + sum(((e.shield + e.health) * e.calculate_dps_vs_target(unit) / max(8, e.distance_to(unit)) for e in enemies)) * enemies.amount
                friendsValue = biasValue + sum(((f.shield + f.health) * f.calculate_dps_vs_target(enemy) / max(8, f.distance_to(unit)) for f in friends)) * friends.amount

                biasDistance = 12
                enemyDistance = biasDistance + enemy.distance_to(self.center)
                friendDistance = biasDistance + unit.distance_to(self.enemyCenter)

                localAdvantage = 1
                localAdvantage *= pow(friendDistance / enemyDistance, 0.666)
                localAdvantage *= pow(friendsValue / enemyValue, 1.0)
                localAdvantage *= pow(self.advantage, 0.666)

                if unit.type_id is UnitTypeId.QUEEN and not self.has_creep(unit):
                    localAdvantage = 0

                # orderTarget = unit.position.towards(enemy, math.copysign(12, localAdvantage - 1))

                if enemy.type_id in CHANGELINGS:
                    unit.attack(enemy)
                elif localAdvantage < 1:
                    if math.modf(unit.tag  * PHI)[0] < localAdvantage:
                        unit.move(unit.position.towards(enemy, -12))
                    elif 5 < unit.distance_to(retreatPoint):
                        unit.move(retreatPoint)
                else:
                    unit.attack(enemy.position)


        elif neutrals.exists:
            for u in army.idle.exclude_type(UnitTypeId.BANELING):
                u.attack(neutrals.closest_to(u))
        else:
            for u in army.idle:
                u.attack(self.getScoutTarget(towardEnemy=True))

    def getChain(self):
        return [self.macro]

    async def getTargetPosition(self, target: UnitTypeId, trainer: UnitTypeId):
        if target in STATIC_DEFENSE[self.race]:
            defenses = self.structures(STATIC_DEFENSE[self.race])
            undefendedTownhalls = self.townhalls.filter(lambda t : not defenses.closer_than(8, t).exists)
            if undefendedTownhalls.exists:
                townhall = undefendedTownhalls.closest_to(trainer)
                # if townhall.position in self.expansion_locations_list:
                #     return self.expansion_locations_dict[townhall.position].center
                # else:
                return townhall.position.towards(self.game_info.map_center, -3)
            # else:
            #     return self.townhalls.random.position.towards(self.game_info.map_center, -7)
        elif self.isStructure(target):
            if target in race_townhalls[self.race]:
                return await self.getNextExpansion()
            else:
                position = self.townhalls.closest_to(self.start_location).position
                return position.towards(self.game_info.map_center, 4)
        else:
            return trainer.position

        return None

    def getTargets(self):
        return []

    async def on_before_start(self):
        pass

    async def on_start(self):
        self.mapSize = max((self.start_location.distance_to(b) for b in self.enemy_start_locations))
        self.greetedOpponent = False

    async def on_step(self, iteration: int):

        self.center = center(self.structures)

        enemies = self.enemy_structures
        if enemies.exists:
            self.enemyCenter = center(enemies)
        else:
            self.enemyCenter = self.enemy_start_locations[0]

        self.iteration = iteration

        if not self.townhalls.exists:
            return
 
        self.assignWorker()
        self.micro()

        chain = self.getChain()
        reserve = Reserve()
        
        for step in chain:
            reserve = step(reserve)
            if inspect.iscoroutine(reserve):
                reserve = await reserve

        # if 0 < len(reserve.items):
        #     print(reserve)

        pass

    async def on_end(self, game_result: Result):
        pass

    async def on_building_construction_started(self, unit: Unit):
        pass

    async def on_building_construction_complete(self, unit: Unit):
        if unit.type_id in race_townhalls[self.race] and self.mineral_field.exists:
            mf = self.mineral_field.closest_to(unit)
            unit.smart(mf)

    async def on_enemy_unit_entered_vision(self, unit: Unit):
        pass

    async def on_enemy_unit_left_vision(self, unit_tag: int):
        pass

    async def on_unit_created(self, unit: Unit):
        pass
    async def on_unit_destroyed(self, unit_tag: int):
        pass

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float):
        if unit.type_id == UnitTypeId.OVERLORD:
            enemies = self.enemy_units | self.enemy_structures
            if enemies.exists:
                enemy = enemies.closest_to(unit)
                unit.move(unit.position.towards(enemy.position, -20))
            else:
                unit.move(unit.position.towards(self.start_location, 20))
        elif (
            unit.is_structure
            and not unit.is_ready
            and unit.health_percentage < 0.333 * unit.build_progress * unit.build_progress
        ):
            unit(AbilityId.CANCEL)
        elif (
            50 <= unit.health_max - unit.health
        ):
            for queen in self.units(UnitTypeId.QUEEN):
                if queen.tag in self.injectQueens:
                    continue
                if 7 < queen.distance_to(unit):
                    continue
                ability = AbilityId.TRANSFUSION_TRANSFUSION
                if ability in await self.get_available_abilities(queen):
                    queen(ability, unit)
        

    async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId):
        if unit.type_id == UnitTypeId.LAIR:
            ability = AbilityId.BEHAVIOR_GENERATECREEPON
            for overlord in self.units(UnitTypeId.OVERLORD):
                if ability in await self.get_available_abilities(overlord):
                    overlord(ability)

    async def on_upgrade_complete(self, upgrade: UpgradeId):
        pass

    async def getNextExpansion(self):
        bases = []
        for base, resources in self.expansion_locations_dict.items():
            if base in self.owned_expansions:
                continue
            if self.townhalls.closer_than(3, base).exists:
                continue
            if not resources.filter(lambda r : r.is_mineral_field).exists:
                continue
            distance = await self.client.query_pathing(self.start_location, base)
            if distance is not None:
                bases.append((base, distance))
        if 0 == len(bases):
            return None
        else:
            bases = sorted(bases, key=lambda p : p[1])
            return bases[0][0]

    def hasCapacity(self, unit: Unit) -> bool:
        if self.isStructure(unit.type_id):
            if unit.has_reactor:
                return len(unit.orders) < 2
            else:
                return unit.is_idle
        else:
            return True

    async def spreadCreep(self, spreader=None, numAttempts=3):

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

        # target = None
        # for _ in range(numAttempts):
        #     position = np.random.uniform(0, self.mapSize, 2)
        #     position = Point2(tuple(position))
        #     if not self.in_map_bounds(position):
        #         continue
        #     if self.has_creep(position):
        #         continue
        #     if self.is_visible(position):
        #         continue
        #     if not self.in_placement_grid(position):
        #         continue
        #     if 10 < spreader.distance_to(position):
        #         position = spreader.position.towards(position, 10)
        #     target = position
        #     break

        target = spreader.position.towards(self.center, -10)

        if spreader.distance_to(self.center) < .1 * self.mapSize:
            target = spreader.position.towards(self.getScoutTarget(True), 10)
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

    async def microQueens(self):


        queens = self.units(UnitTypeId.QUEEN)
        hatcheries = sorted(self.townhalls, key=lambda h: h.tag)
        queens = sorted(queens, key=lambda q: q.tag)
        assignment = list(zip(hatcheries[:4], queens))

        self.injectQueens = [ q.tag for h, q in assignment]

        for hatchery, queen in assignment:
            if not queen.is_idle:
                continue
            abilities = await self.get_available_abilities(queen)
            if AbilityId.EFFECT_INJECTLARVA in abilities and hatchery.is_ready:
                    queen(AbilityId.EFFECT_INJECTLARVA, hatchery)
            elif 5 < queen.distance_to(hatchery):
                queen.attack(hatchery.position)
        for queen in queens:
            if queen.tag in self.injectQueens:
                continue
            if not queen.is_idle:
                continue
            abilities = await self.get_available_abilities(queen)
            if AbilityId.BUILD_CREEPTUMOR_QUEEN in abilities:
                await self.spreadCreep(spreader=queen)
            elif 5 < queen.distance_to(self.center):
                queen.attack(self.center)


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
            target = self.getScoutTarget(towardEnemy=True)
            changeling.move(target)

    def getScoutTarget(self, towardEnemy=False, uniformBias=0.1):
        # p = [
        #     (uniformBias * self.mapSize + b.distance_to(self.enemy_start_locations[0])) / (uniformBias * self.mapSize + b.distance_to(self.start_location))
        #     for b in self.expansion_locations_list
        # ]
        # if towardEnemy:
        #     p = [1.0 / pi for pi in p]
        # ps = sum(p)
        # p = [pi / ps for pi in p]

        # bi = np.random.choice(range(len(p)), p=p)
        # target = self.expansion_locations_list[bi]

        target = random.choice(self.expansion_locations_list)
        
        return target

    def moveOverlord(self, bias=1):
        overlords = self.units(withEquivalents(UnitTypeId.OVERLORD)).idle
        if overlords.exists:
            overlord = overlords.random
            target = self.getScoutTarget()
            overlord.move(target)

    def isStructure(self, unit):
        if unit.value not in self.game_data.units:
            return False
        unitData = self.game_data.units[unit.value]
        return IS_STRUCTURE in unitData.attributes

    def getSupplyBuffer(self):
        supplyBuffer = 0
        supplyBuffer += self.townhalls.amount
        supplyBuffer += self.larva.amount
        supplyBuffer += 3 * self.count(UnitTypeId.QUEEN)
        supplyBuffer += 2 * self.count(UnitTypeId.BARRACKS)
        supplyBuffer += 2 * self.count(UnitTypeId.FACTORY)
        supplyBuffer += 2 * self.count(UnitTypeId.STARPORT)
        supplyBuffer += 2 * self.count(UnitTypeId.GATEWAY)
        supplyBuffer += 2 * self.count(UnitTypeId.WARPGATE)
        supplyBuffer += 2 * self.count(UnitTypeId.ROBOTICSFACILITY)
        supplyBuffer += 2 * self.count(UnitTypeId.STARGATE)
        return supplyBuffer

    def getSupplyTarget(self):

        unit = SUPPLY[self.race]
        if self.isStructure(unit):
            supplyActual = self.structures(unit).ready.amount
        else:
            supplyActual = self.units(unit).ready.amount
        if self.supply_cap == 200:
            return supplyActual
            
        supplyPending = 8 * self.already_pending(unit)
        supplyPending += sum((6 * h.build_progress for h in self.structures(UnitTypeId.HATCHERY).not_ready))
        supplyPending += sum((15 * h.build_progress for h in self.structures(UnitTypeId.NEXUS).not_ready))
        supplyPending += sum((15 * h.build_progress for h in self.structures(UnitTypeId.COMMANDCENTER).not_ready))
        supplyBuffer = self.getSupplyBuffer()
        supplyNeeded = 1 + math.floor((supplyBuffer - self.supply_left - supplyPending) / 8)

        return supplyActual + supplyNeeded

    def count(self, unit):
        count = 0
        count += self.structures(unit).amount
        count += self.units(unit).amount
        if type(unit) is UnitTypeId:
            unit = { unit }
        for u in unit:
            if u is UnitTypeId.ZERGLING:
                count += 2 * self.already_pending(u)
            else:
                count += self.already_pending(u)
        return count

    async def reachTarget(self, target, reserve):

        if self.tech_requirement_progress(target) < 1:
            return reserve

        if type(target) is UnitTypeId:
            trainerTypes = UNIT_TRAINED_FROM[target]
        elif type(target) is UpgradeId:
            if target in self.state.upgrades:
                return reserve
            elif self.already_pending_upgrade(target):
                return reserve
            trainerTypes = UPGRADE_RESEARCHED_FROM[target]
        else:
            return reserve

        trainers = self.structures(trainerTypes) | self.units(trainerTypes)
        trainers = trainers.ready
        # trainers = trainers.sorted_by_distance_to(center(self.townhalls))
        
        for trainer in trainers:

            if trainer.tag in reserve.trainers:
                continue

            if not self.hasCapacity(trainer):
                continue

            if type(target) is UnitTypeId:
                info = TRAIN_INFO[trainer.type_id][target]
            elif type(target) is UpgradeId:
                info = RESEARCH_INFO[trainer.type_id][target]
            else:
                continue

            if "requires_techlab" in info and not trainer.has_techlab:
                continue

            ability = info["ability"]

            if "required_building" in info:
                building = info["required_building"]
                building = withEquivalents(building)
                if not self.structures(building).ready.exists:
                    continue
            if "required_upgrade" in info:
                upgrade = info["required_upgrade"]
                if not upgrade in self.state.upgrades:
                    continue

            if not self.canAffordWithReserve(target, reserve):
                reserve = reserve + self.createReserve(target, trainer)
                break

            abilities = await self.get_available_abilities(trainer)
            if not ability in abilities:
                # print(abilities)
                continue

            if target in ALL_GAS:
                geysers = []
                for b in self.owned_expansions.keys():
                    geysers += [g for g in self.expansion_locations_dict[b] if g.is_vespene_geyser]
                geysers = Units(geysers, self)
                geysers = geysers.filter(lambda g : not self.gas_buildings.closer_than(1, g).exists)
                # geysers = geysers.filter(lambda g : not self.workers.filter(lambda w : w.order_target == g.tag).exists)
                if not geysers.exists:
                    continue
                abilityTarget = geysers.closest_to(trainer.position)
            elif "requires_placement_position" in info:
                position = await self.getTargetPosition(target, trainer)
                if not position:
                    continue
                withAddon = target in { UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT }
                abilityTarget = await self.find_placement(ability, position, max_distance=8, placement_step=1, addon_place=withAddon)
            else:
                abilityTarget = None

            reserve = reserve + self.createReserve(None, trainer)

            if trainer.is_carrying_resource:
                trainer.return_resource()
                queue = True
            else:
                queue = False

            if abilityTarget is None:
                assert(trainer(ability, queue=queue))
            else:
                assert(trainer(ability, target=abilityTarget, queue=queue))

            break

        return reserve

    def unitValue(self, unit):
        value = self.calculate_unit_value(unit)
        return value.minerals + 2 * value.vespene

    def assignWorker(self):

        gasActual = sum((g.assigned_harvesters for g in self.gas_buildings))

        worker = None
        target = None

        if self.workers.idle.exists and self.townhalls.ready.exists:
            worker = self.workers.idle.random
            townhall = self.townhalls.ready.random
            minerals = self.mineral_field.closest_to(townhall)
            target = minerals

        if worker is None:
            for gas in self.gas_buildings.ready:
                workers = self.workers.filter(lambda w : w.order_target == gas.tag)
                if workers.exists and (0 < gas.surplus_harvesters or self.gasTarget + 1 < gasActual):
                    worker = workers.furthest_to(gas)
                elif gas.surplus_harvesters < 0 and gasActual < self.gasTarget:
                    target = gas

        if worker is None:
            for townhall in self.townhalls.ready:
                if 0 < townhall.surplus_harvesters or target is not None:
                    workers = self.workers.closer_than(5, townhall)
                    if workers.exists:
                        worker = workers.random
                        break

        if worker is None:
            return False

        if target is None:
            for gas in self.gas_buildings.ready:
                if gas.surplus_harvesters < 0 and gasActual + 1 < self.gasTarget:
                    target = gas
                    break

        if target is None:
            for townhall in self.townhalls.ready:
                if townhall.surplus_harvesters < 0:
                    minerals = self.mineral_field.closest_to(townhall)
                    target = minerals

        if target is None:
            return False

        if worker.is_carrying_resource:
            worker.return_resource()
            worker.gather(target, queue=True)
        else:
            worker.gather(target)

        return True

    async def macro(self, reserve):
        targets = self.getTargets()
        for target in targets:
            reserve = await self.reachTarget(target, reserve)
        return reserve

    def canAffordWithReserve(self, item, reserve):
        cost = self.createReserve(item)
        if (
            (cost.minerals == 0 or cost.minerals + reserve.minerals <= self.minerals)
            and (cost.vespene == 0 or cost.vespene + reserve.vespene <= self.vespene)
            and (cost.food == 0 or cost.food + reserve.food <= self.supply_left)
        ):
            return True
        else:
            return False

    def getMaxWorkers(self):
        workers = 0
        for loc in self.owned_expansions.keys():
            base = self.expansion_locations_dict[loc]
            minerals = base.filter(lambda m : m.is_mineral_field)
            workers += 2 * minerals.amount
        geysers = self.gas_buildings.filter(lambda g : g.has_vespene)
        workers += 3 * geysers.amount
        return workers

    def createReserve(self, item=None, trainer=None):
        if item is None:
            cost = Cost(0, 0)
            names = []
        else:
            cost = self.calculate_cost(item)
            names = [item.name]
        if not isinstance(item, UnitTypeId):
            food = 0
        else:
            food = int(self.calculate_supply_cost(item))
        if trainer is None:
            tag = 0
        else:
            tag = trainer.tag
        return Reserve(cost.minerals, cost.vespene, food, [tag], names)

    def canPlace(self, position, unit):
        if unit in UNIT_TECH_ALIAS:
            unit = list(UNIT_TECH_ALIAS[unit])[0]
        trainer = list(UNIT_TRAINED_FROM[unit])[0]
        ability = TRAIN_INFO[trainer][unit]["ability"]
        abilityData = self.game_data.abilities[ability.value]
        return self.can_place_single(abilityData, position)

    def canPlaceAddon(self, position):
        addonPosition = position + Point2((2.5, -0.5))
        return self.canPlace(addonPosition, UnitTypeId.SUPPLYDEPOT)

    def isBlockingExpansion(self, position):
        return any((e.distance_to(position) < 4.25 for e in self.expansion_locations_list))