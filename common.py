
import inspect
import itertools
import time

import math
import random
from typing import Iterable, Union, Coroutine, Set, List, Callable
from numpy.lib.function_base import insert
from s2clientprotocol.error_pb2 import CantAddMoreCharges

from sc2.game_data import Cost
from utils import CHANGELINGS, armyValue, canAttack, center, dot, filterArmy, withEquivalents

import numpy as np
import json
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
        self.gasTarget = 0
        self.advantage = 0
        self.armyBlacklist = {}
        self.timing = {}
        self.printTiming = False
        self.printReserve = False

    async def on_before_start(self):
        pass

    async def on_start(self):
        self.client.game_step = 4

    async def on_step(self, iteration: int):

        if self.townhalls.empty:
            return

        self.center = center(self.structures)
        if self.enemy_structures.exists:
            self.enemyCenter = center(self.enemy_structures)
        else:
            self.enemyCenter = self.enemy_start_locations[0]

        targets = self.getTargets()
        reserve = Reserve()
        for target in targets:
            reserve = await self.reachTarget(target, reserve)
            if self.minerals < reserve.minerals:
                break

        if self.printReserve and reserve.items:
            print(reserve)

    async def on_end(self, game_result: Result):
        pass

    async def on_building_construction_started(self, unit: Unit):
        pass

    async def on_building_construction_complete(self, unit: Unit):
        if unit.type_id in race_townhalls[self.race] and self.mineral_field.exists:
            unit.smart(self.mineral_field.closest_to(unit))

    async def on_enemy_unit_entered_vision(self, unit: Unit):
        pass

    async def on_enemy_unit_left_vision(self, unit_tag: int):
        pass

    async def on_unit_created(self, unit: Unit):
        pass

    async def on_unit_destroyed(self, unit_tag: int):
        pass

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float):
        if (
            unit.is_structure
            and not unit.is_ready
            and unit.health_percentage < 0.333 * unit.build_progress * unit.build_progress
        ):
            unit(AbilityId.CANCEL)
        

    async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId):
        if unit.type_id == UnitTypeId.LAIR:
            ability = AbilityId.BEHAVIOR_GENERATECREEPON
            for overlord in self.units(UnitTypeId.OVERLORD):
                if ability in await self.get_available_abilities(overlord):
                    overlord(ability)

    async def on_upgrade_complete(self, upgrade: UpgradeId):
        pass

    def getTargets(self) -> List[Union[UnitTypeId, UpgradeId]]:
        return []

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
        army = army.tags_not_in(self.armyBlacklist)

        enemyArmy = self.enemy_units | self.enemy_structures
        enemyArmy = enemyArmy.exclude_type(withEquivalents(UnitTypeId.OVERLORD))
        enemyArmy = enemyArmy.exclude_type(withEquivalents(UnitTypeId.OVERSEER))
        enemyArmy = enemyArmy.exclude_type(withEquivalents(UnitTypeId.OBSERVER))
        enemyArmy = enemyArmy.sorted_by_distance_to(self.center)

        # neutrals = self.enemy_units(CIVILIANS)
        # rocks = self.all_units.filter(lambda r: "Destructible" in r.name)

        # if self.destroyRocks:
        #     neutrals |= rocks

        # enemyArmy |= neutrals


        for unit in army:

            # enemies = enemyArmy.filter(lambda e : canAttack(e, unit))
            # friends = set().union(*[army.filter(lambda f : canAttack(f, e)) for e in enemies])
            # friends = Units(friends, self)
            # friends = friends.tags_not_in({ unit.tag })

            enemies = enemyArmy.closer_than(12, unit)
            friends = army.closer_than(12, unit)

            biasValue = 1000
            enemyValue = biasValue + armyValue(enemies) * len(enemies)
            friendsValue = biasValue + armyValue(friends) * len(friends)

            biasDistance = 32
            enemyDistance = biasDistance + unit.distance_to(self.center)
            friendDistance = biasDistance + unit.distance_to(self.enemyCenter)

            localAdvantage = 1
            localAdvantage *= pow(friendsValue / enemyValue, 1)
            localAdvantage *= pow(self.advantage, .2)
            localAdvantage *= pow(friendDistance / enemyDistance, .2)
            localAdvantage *= pow(unit.health_percentage, .2)

            if enemies.exists:
                if localAdvantage < 1:
                    unit.move(unit.position.towards(enemies.center, -12))
                elif not unit.is_idle:
                    unit.attack(enemies.center)
            elif enemyArmy.exists:
                target = enemyArmy.random
                unit.attack(target.position)
            elif unit.is_idle:
                unit.attack(random.choice(self.expansion_locations_list))

    def getTechDistanceForTrainer(self, unit: UnitTypeId, trainer: UnitTypeId) -> int:
        info = TRAIN_INFO[trainer][unit]
        structure = info.get("required_building")
        if structure is None:
            return 0
        elif self.structures(structure).ready.exists:
            return 0
        else:
            return 1 + self.getTechDistance(structure)

    def getTechDistance(self, unit: UnitTypeId) -> int:
        trainers = UNIT_TRAINED_FROM.get(unit)
        if not trainers:
            return 0
        return min((self.getTechDistanceForTrainer(unit, t) for t in trainers))

    def getTargetPosition(self, target: UnitTypeId, trainer: UnitTypeId) -> Point2:
        if target in STATIC_DEFENSE[self.race]:
            return self.townhalls.random.position.towards(self.game_info.map_center, -7)
        elif self.isStructure(target):
            if target in race_townhalls[self.race]:
                return self.getNextExpansion()
            else:
                position = self.townhalls.closest_to(self.start_location).position
                return position.towards(self.game_info.map_center, 4)
        else:
            return trainer.position

    def getNextExpansion(self) -> Point2:
        bases = [
            base
            for base, resources in self.expansion_locations_dict.items()
            if (
                not base in self.owned_expansions
                and not self.townhalls.closer_than(3, base).exists
                and resources.filter(lambda r : r.is_mineral_field or r.has_vespene).exists
            )
        ]
        if not bases:
            return None
        bases = sorted(bases, key=lambda b : b.distance_to(self.start_location))
        return bases[0]

    def hasCapacity(self, unit: Unit) -> bool:
        if self.isStructure(unit.type_id):
            if unit.has_reactor:
                return len(unit.orders) < 2
            else:
                return unit.is_idle
        else:
            return True

    def isStructure(self, unit: UnitTypeId) -> bool:
        unitData = self.game_data.units.get(unit.value)
        if unitData is None:
            return False
        return IS_STRUCTURE in unitData.attributes

    def getSupplyBuffer(self) -> int:
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

    def getSupplyPending(self) -> int:
        supplyPending = 0
        supplyPending = 8 * self.already_pending(SUPPLY[self.race])
        if self.race is Race.Zerg:
            supplyPending += sum((6 * h.build_progress for h in self.structures(UnitTypeId.HATCHERY).not_ready))
        elif self.race is Race.Protoss:
            supplyPending += sum((15 * h.build_progress for h in self.structures(UnitTypeId.NEXUS).not_ready))
        elif self.race is Race.Terran:
            supplyPending += sum((15 * h.build_progress for h in self.structures(UnitTypeId.COMMANDCENTER).not_ready))
        return supplyPending

    def getSupplyTarget(self) -> int:

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

    def count(self, unit: Union[UnitTypeId, Set[UnitTypeId]]) -> int:
        count = 0
        count += self.structures(unit).amount
        count += self.units(unit).amount
        if unit in UnitTypeId:
            unit = { unit }
        for u in unit:
            if u is UnitTypeId.ZERGLING:
                count += 2 * self.already_pending(u)
            else:
                count += self.already_pending(u)
        return count

    async def reachTarget(self, target: Union[UnitTypeId, UpgradeId], reserve: Reserve) -> Coroutine[any, any, Reserve]:

        if type(target) is UnitTypeId:
            if self.tech_requirement_progress(target) < 1:
                return reserve
            trainerTypes = UNIT_TRAINED_FROM[target]
        elif type(target) is UpgradeId:
            if target in self.state.upgrades:
                return reserve
            elif self.already_pending_upgrade(target):
                return reserve
            trainerTypes = UPGRADE_RESEARCHED_FROM[target]

        trainers = self.structures(trainerTypes) | self.units(trainerTypes)
        trainers = trainers.ready
        trainers = trainers.tags_not_in(reserve.trainers)
        trainers = trainers.filter(lambda t: self.hasCapacity(t))
        
        for trainer in trainers:

            if type(target) is UnitTypeId:
                info = TRAIN_INFO[trainer.type_id][target]
            elif type(target) is UpgradeId:
                info = RESEARCH_INFO[trainer.type_id][target]

            if "requires_techlab" in info and not trainer.has_techlab:
                continue

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
                reserve = reserve + self.createReserve(target, [trainer.tag])
                break

            ability = info["ability"]
            abilities = await self.get_available_abilities(trainer)
            if not ability in abilities:
                continue

            if target in ALL_GAS:
                geysers = []
                for b, h in self.owned_expansions.items():
                    if not h.is_ready:
                        continue
                    geysers.extend(g for g in self.expansion_locations_dict[b].vespene_geyser)
                if not geysers:
                    continue
                abilityTarget = random.choice(geysers)
            elif "requires_placement_position" in info:
                position = self.getTargetPosition(target, trainer)
                if not position:
                    continue
                withAddon = target in { UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT }
                abilityTarget = await self.find_placement(ability, position, max_distance=8, placement_step=1, addon_place=withAddon)
            else:
                abilityTarget = None

            reserve = reserve + self.createReserve(None, [trainer.tag])

            queue = False
            if trainer.is_carrying_resource:
                trainer.return_resource()
                queue = True

            assert(trainer(ability, target=abilityTarget, queue=queue))

            break

        return reserve

    def unitValue(self, unit: UnitTypeId) -> int:
        value = self.calculate_unit_value(unit)
        return value.minerals + 2 * value.vespene

    def assignWorker(self):

        gasActual = sum((g.assigned_harvesters for g in self.gas_buildings))

        worker = None
        target = None

        # if self.workers.idle.exists and self.townhalls.ready.exists:
        #     worker = self.workers.idle.random
        #     townhall = self.townhalls.ready.random
        #     minerals = self.mineral_field.closest_to(townhall)
        #     target = minerals

        if self.workers.idle.exists:
            worker = self.workers.idle.random

        if worker is None:
            for gas in self.gas_buildings.ready:
                workers = self.workers.filter(lambda w : w.order_target == gas.tag)
                if workers.exists and (0 < gas.surplus_harvesters or self.gasTarget + 1 < gasActual):
                    worker = workers.furthest_to(gas)
                elif gas.surplus_harvesters < 0 and gasActual + 1 < self.gasTarget:
                    target = gas

        if worker is None:
            for townhall in self.townhalls.ready:
                if 0 < townhall.surplus_harvesters or target is not None:
                    workers = self.workers.closer_than(5, townhall)
                    if workers.exists:
                        worker = workers.random
                        break

        if worker is None:
            return

        # if target is None:
        #     for gas in self.gas_buildings.ready:
        #         if gas.surplus_harvesters < 0 and gasActual + 1 < self.gasTarget:
        #             target = gas
        #             break

        if target is None:
            for townhall in self.townhalls.ready:
                if townhall.surplus_harvesters < 0:
                    minerals = self.mineral_field.closest_to(townhall)
                    target = minerals

        if target is None:
            return

        if worker.is_carrying_resource:
            worker.return_resource()
            worker.gather(target, queue=True)
        else:
            worker.gather(target)

    def canAffordWithReserve(self, item: Union[UnitTypeId, UpgradeId, AbilityId], reserve: Reserve) -> bool:
        cost = self.createReserve(item)
        if cost.minerals and self.minerals < reserve.minerals + cost.minerals:
            return False
        elif cost.vespene and self.vespene < reserve.vespene + cost.vespene:
            return False
        elif cost.food and self.supply_left < reserve.food + cost.food:
            return False
        else:
            return True

    def getMaxWorkers(self) -> int:
        workers = 0
        for loc in self.owned_expansions.keys():
            base = self.expansion_locations_dict[loc]
            minerals = base.filter(lambda m : m.is_mineral_field)
            workers += 2 * minerals.amount
        geysers = self.gas_buildings.filter(lambda g : g.has_vespene)
        workers += 3 * geysers.amount
        return workers

    def createReserve(self, item: Union[UnitTypeId, UpgradeId, AbilityId], tags = []) -> Reserve:
        cost = Cost(0, 0)
        names = []
        food = 0
        tags = []
        if item is not None:
            cost = self.calculate_cost(item)
            names.append(item.name)
        if item in UnitTypeId:
            food = int(self.calculate_supply_cost(item))
        return Reserve(cost.minerals, cost.vespene, food, tags, names)

    async def canPlace(self, position: Point2, unit: UnitTypeId) -> Coroutine[any, any, bool]:
        aliases = UNIT_TECH_ALIAS.get(unit)
        if aliases:
            return any((await self.canPlace(position, a) for a in aliases))
        trainers = UNIT_TRAINED_FROM.get(unit)
        if not trainers:
            return False
        for trainer in trainers:
            ability = TRAIN_INFO[trainer][unit]["ability"]
            abilityData = self.game_data.abilities[ability.value]
            if await self.can_place_single(abilityData, position):
                return True
        return False

    def isBlockingExpansion(self, position: Point2) -> bool:
        return any((e.distance_to(position) < 4.25 for e in self.expansion_locations_list))