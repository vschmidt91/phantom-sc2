
from numpy.core.fromnumeric import sort
from numpy.lib.shape_base import expand_dims
from macro_objective import MacroObjective
from cost import Cost
from collections import Counter
import inspect
import itertools
import time
import io

import math
import random
from typing import Iterable, Optional, Tuple, Union, Coroutine, Set, List, Callable
from numpy.lib.function_base import insert
from s2clientprotocol.error_pb2 import CantAddMoreCharges, Error

from utils import CHANGELINGS, armyValue, unitPriority, canAttack, center, dot, filterArmy, unitValue, withEquivalents

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

SUPPLY_PROVIDED = {
    UnitTypeId.PYLON: 8,
    UnitTypeId.SUPPLYDEPOT: 8,
    UnitTypeId.OVERLORD: 8,
    UnitTypeId.NEXUS: 15,
    UnitTypeId.HATCHERY: 6,
    UnitTypeId.LAIR: 6,
    UnitTypeId.HIVE: 6,
    UnitTypeId.COMMANDCENTER: 15,
    UnitTypeId.COMMANDCENTERFLYING: 15,
    UnitTypeId.ORBITALCOMMAND: 15,
    UnitTypeId.ORBITALCOMMANDFLYING: 15,
    UnitTypeId.PLANETARYFORTRESS: 15,
}

CIVILIANS = set()
CIVILIANS = { UnitTypeId.SCV, UnitTypeId.MULE, UnitTypeId.PROBE }
CIVILIANS |= withEquivalents(UnitTypeId.DRONE)
CIVILIANS |= withEquivalents(UnitTypeId.QUEEN)
CIVILIANS |= withEquivalents(UnitTypeId.OVERLORD)
CIVILIANS |= withEquivalents(UnitTypeId.BROODLING)
# CIVILIANS |= withEquivalents(UnitTypeId.OVERSEER)
CIVILIANS |= withEquivalents(UnitTypeId.OBSERVER)
CIVILIANS |= { UnitTypeId.LARVA, UnitTypeId.EGG }
CIVILIANS |= CHANGELINGS

TRAINABLE_UNITS = set(u for e in TRAIN_INFO.values() for u in e.keys())
TRAIN_ABILITIES = {
    u: [e[u]["ability"] for e in TRAIN_INFO.values() if u in e]
    for u in TRAINABLE_UNITS
}

UNIT_BY_TRAIN_ABILITY = {
    unit_element["ability"] : unit
    for trainer_element in TRAIN_INFO.values()
    for unit, unit_element in trainer_element.items()
}

UPGRADE_BY_RESEARCH_ABILITY = {
    upgrade_element["ability"] : upgrade
    for research_element in RESEARCH_INFO.values()
    for upgrade, upgrade_element in research_element.items()
}

class CommonAI(BotAI):

    def __init__(self, game_step: int = 1):

        try:
            with open('quotes.txt', 'r') as file:
                self.quotes = file.readlines()
        except:
            self.quotes = None

        self.raw_affects_selection = True
        self.destroyRocks = False
        self.gasTarget = 0
        self.advantage = 0
        self.armyBlacklist = {}
        self.timing = {}
        self.printTiming = False
        self.printReserve = False
        self.macroObjectives = []
        self.game_step = game_step
        self.pending = Counter()

    async def on_before_start(self):
        pass

    async def on_start(self):

        if self.quotes:
            quote = random.choice(self.quotes)
            await self.client.chat_send(quote, False)

        self.client.game_step = self.game_step
        self.expansion_distances = {
            b: await self.get_base_distance(b)
            for b in self.expansion_locations_list
        }

    async def on_step(self, iteration: int):

        # if iteration == 0:

        for error in self.state.action_errors:
            unit = UNIT_BY_TRAIN_ABILITY.get(error.exact_id)
            if unit and unit in self.pending:
                self.pending.subtract((unit,))
        # if self.state.action_errors:
        #     print('action_errors', self.state.action_errors)
        # if self.state.alerts:
        #     print(self.state.alerts)

    def count_planned(self, items) -> int:
        if type(items) is not set:
            items = { items }
        return sum(1 for t in self.macroObjectives if t.item in items)

    def count_pending(self, item) -> int:
        if type(item) is set:
            return sum(self.count_pending(u) for u in item)
        if type(item) is UnitTypeId:
            # if self.isStructure(item):
                ability = self.game_data.units[item.value].creation_ability
                return self._abilities_all_units[0][ability]
            # else:
            #     return self.pending[item]
        elif type(item) is UpgradeId:
            return self.pending[item]
            # ability = self.game_data.upgrades[item.value].research_ability
            # return self._abilities_all_units[0][ability]
        else:
            raise TypeError()

    def estimate_income(self):
        harvesters_on_minerals = sum(t.assigned_harvesters for t in self.townhalls)
        harvesters_on_vespene = sum(g.assigned_harvesters for g in self.gas_buildings)
        income_minerals = 50 * harvesters_on_minerals / 60
        income_vespene = 55 * harvesters_on_vespene / 60
        return income_minerals, income_vespene

    def time_to_harvest(self, minerals, vespene):
        income_minerals, income_vespene = self.estimate_income()
        time_minerals = minerals / max(1, income_minerals)
        time_vespene = vespene / max(1, income_vespene)
        return max(0, time_minerals, time_vespene)

    def time_to_reach(self, unit, target):
        return unit.position.distance_to(target.position) / max(.01, unit.movement_speed)

    async def reachMacroObjective(self):

        reserve = Cost(0, 0, 0)
        units = { t.unit.tag for t in self.macroObjectives if t.unit is not None }
        nextMacroObjectives = list(self.macroObjectives)

        for objective in self.macroObjectives:

            if objective.cost is None:
                objective.cost = self.getCost(objective.item)

            if objective.unit is None:
                objective.unit, objective.ability = await self.findTrainer(objective.item, exclude=units)

            if objective.unit is None:
                # reserve += objective.cost
                continue

            units.add(objective.unit.tag)

            if objective.target is None:
                try:
                    objective.target = await self.getTarget(objective)
                except: 
                    continue

            if objective.target is not None and objective.unit.movement_speed and len(objective.unit.orders) < 2:
                minerals_needed = objective.cost.minerals + reserve.minerals - self.minerals
                vespene_needed = objective.cost.vespene + reserve.vespene - self.vespene
                if self.time_to_harvest(minerals_needed, vespene_needed) < self.time_to_reach(objective.unit, objective.target):
                    
                    if type(objective.target) is Unit:
                        move_to = objective.target.position
                    else:
                        move_to = objective.target
                    if objective.unit.is_carrying_resource:
                        objective.unit.return_resource()
                        objective.unit.move(move_to, queue=True)
                    else:
                        objective.unit.move(move_to)

            if not self.canAffordWithReserve(objective.cost, reserve=reserve):
                reserve += objective.cost
                continue

            abilities = await self.get_available_abilities(objective.unit)
            if not objective.ability["ability"] in abilities:
                # print("ability failed:" + str(objective))
                objective.unit = None
                objective.target = None
                break

            queue = False
            if objective.unit.is_carrying_resource:
                objective.unit.return_resource()
                queue = True

            if not objective.unit(objective.ability["ability"], target=objective.target, queue=queue):
                # print("objective failed:" + str(objective))
                # reserve += objective.cost
                objective.unit = None
                objective.target = None
                break

            self.pending.update((objective.item,))

            nextMacroObjectives.remove(objective)
            break

        self.macroObjectives = sorted(nextMacroObjectives, key=lambda o:-o.priority)

    def get_owned_geysers(self):
        for b, h in self.owned_expansions.items():
            if not h.is_ready:
                continue
            for g in self.expansion_locations_dict[b].vespene_geyser:
                yield g

    async def getTarget(self, objective: MacroObjective) -> Coroutine[any, any, Union[Unit, Point2]]:
        if objective.item in ALL_GAS:
            geysers = [
                g
                for g in self.get_owned_geysers()
                if not any(e.position == g.position for e in self.gas_buildings)
            ]
            if not geysers:
                raise Exception()
            # return sorted(geysers, key=lambda g:g.tag)[0]
            return random.choice(geysers)
        elif "requires_placement_position" in objective.ability:
            position = await self.getTargetPosition(objective.item, objective.unit)
            withAddon = objective in { UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT }
            if objective.unit == TOWNHALL[self.race]:
                max_distance = 0
            else:
                max_distance = 8
            position = await self.find_placement(objective.ability["ability"], position, max_distance=max_distance, placement_step=1, addon_place=withAddon)
            if position is None:
                raise Exception()
            else:
                return position
        else:
            return None


    def getCost(self, item: Union[UnitTypeId, UpgradeId]) -> Cost:
        cost = self.calculate_cost(item)
        food = 0
        if type(item) is UnitTypeId:
            food = int(self.calculate_supply_cost(item))
        return Cost(cost.minerals, cost.vespene, food)

    async def findTrainer(self, item: Union[UnitTypeId, UpgradeId], exclude: Set[int]) -> Coroutine[any, any, Tuple[Unit, any]]:

        if type(item) is UnitTypeId:
            trainerTypes = UNIT_TRAINED_FROM[item]
        elif type(item) is UpgradeId:
            trainerTypes = UPGRADE_RESEARCHED_FROM[item]

        if item in ALL_GAS:
            ls = { w.tag : len(w.orders) for w in self.workers }
            exclude.add(0)

        trainers = self.structures(trainerTypes) | self.units(trainerTypes)
        trainers = trainers.ready
        trainers = trainers.tags_not_in(exclude)
        trainers = trainers.filter(lambda t: self.hasCapacity(t))

        if not trainers.exists:
            return None, None

        trainers_abilities = await self.get_available_abilities(trainers, ignore_resource_requirements=True)
        
        for trainer, abilities in zip(trainers, trainers_abilities):

            already_training = False
            for order in trainer.orders:
                order_unit = UNIT_BY_TRAIN_ABILITY.get(order.ability.id)
                if order_unit in self.pending:
                    already_training = True
                    break
            if already_training:
                continue

            if type(item) is UnitTypeId:
                ability = TRAIN_INFO[trainer.type_id][item]
            elif type(item) is UpgradeId:
                ability = RESEARCH_INFO[trainer.type_id][item]

            if "requires_techlab" in ability and not trainer.has_techlab:
                continue

            requiredBuilding = ability.get("required_building", None)
            if requiredBuilding is not None:
                requiredBuilding = withEquivalents(requiredBuilding)
                if not self.structures(requiredBuilding).ready.exists:
                    continue

            requiredUpgrade = ability.get("required_upgrade", None)
            if requiredUpgrade is not None:
                if not requiredUpgrade in self.state.upgrades:
                    continue

            if ability["ability"] not in abilities:
                continue
                
            return trainer, ability

        return None, None

    async def on_end(self, game_result: Result):
        pass

    async def on_building_construction_started(self, unit: Unit):
        if unit.type_id in self.pending:
            self.pending.subtract((unit.type_id,))

    async def on_building_construction_complete(self, unit: Unit):
        if unit.type_id in race_townhalls[self.race] and self.mineral_field.exists:
            unit.smart(self.mineral_field.closest_to(unit))

    async def on_enemy_unit_entered_vision(self, unit: Unit):
        pass

    async def on_enemy_unit_left_vision(self, unit_tag: int):
        pass

    async def on_unit_created(self, unit: Unit):
        if unit.type_id in self.pending:
            self.pending.subtract((unit.type_id,))

    async def on_unit_destroyed(self, unit_tag: int):
        pass
        # unit = self.units.by_tag(unit_tag) or self.structures.by_tag(unit_tag)
        # if unit:
        #     for order in unit.orders:
        #         order_unit = UNIT_BY_TRAIN_ABILITY.get(order.ability.id)
        #         if order_unit and order_unit in self.pending:
        #             self.pending.subtract((order_unit,))

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float):
        if (
            unit.is_structure
            and not unit.is_ready
            and unit.health_percentage < 0.333 * unit.build_progress * unit.build_progress
        ):
            unit(AbilityId.CANCEL)
        elif unit.type_id == UnitTypeId.CREEPTUMORBURROWED:
            unit(AbilityId.CANCEL)
        

    async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId):

        if unit.type_id in self.pending:
            self.pending.subtract((unit.type_id,))
        
        # if unit.type_id == UnitTypeId.EGG:
        #     unit_morph = UNIT_BY_TRAIN_ABILITY[unit.orders[0].ability.id]
        #     self.pending.update((unit_morph,))

        await super().on_unit_type_changed(unit, previous_type)

    async def on_upgrade_complete(self, upgrade: UpgradeId):
        if upgrade in self.pending:
            self.pending.subtract((upgrade,))

    def unit_cost(self, unit: Unit) -> int:
        cost = self.game_data.units[unit.type_id.value].cost
        return cost.minerals + cost.vespene

    async def micro(self):

        # if self.time < 7 * 60:
        #     return

        friends = self.units
        friends = friends.exclude_type(CIVILIANS)

        enemies = self.enemy_units
        enemies = enemies.exclude_type(CIVILIANS)

        if not enemies.exists:
            enemies = self.enemy_units
        if not enemies.exclude_type:
            enemies = self.enemy_structures

        if self.enemy_structures.exists:
            enemyBaseCenter = center(self.enemy_structures)
        else:
            enemyBaseCenter = self.enemy_start_locations[0]
        baseCenter = center(self.structures)

        friends_rating_global = sum(self.unit_cost(f) for f in friends)
        enemies_rating_global = sum(self.unit_cost(e) for e in enemies)

        for unit in friends:

            if enemies.exists:

                target = enemies.closest_to(unit)

                friends_rating = sum(unitValue(f) / max(1, target.distance_to(f)) for f in friends)
                enemies_rating = sum(unitValue(e) / max(1, unit.distance_to(e)) for e in enemies)

                distance_bias = 64

                advantage = 1
                # advantage *= friends_rating_global / max(1, enemies_rating_global)
                advantage *= friends_rating / max(1, enemies_rating)
                advantage *= max(1, (distance_bias + target.distance_to(enemyBaseCenter)) / (distance_bias + unit.distance_to(baseCenter)))

                if advantage < .5:

                    if not unit.is_moving:

                        unit.move(unit.position.towards(target, -15))

                elif advantage < 1:

                    if unit.weapon_cooldown:

                        if not unit.is_moving:
                            unit.move(unit.position.towards(target, -15))

                    elif not unit.is_attacking:

                        unit.attack(target.position)
                    
                elif advantage < 2:

                    if not unit.is_attacking:

                        unit.attack(target.position)

                else:

                    if unit.weapon_cooldown:
                        if not unit.is_moving and 1 < unit.distance_to(target):
                            unit.move(unit.position.towards(target.position, 3))
                    elif not unit.is_attacking:
                        unit.attack(target.position)

    
            elif self.destructables.exists:
                unit.attack(self.destructables.closest_to(self.start_location))

            elif unit.is_idle:

                if self.time < 8 * 60:
                    target = random.choice(self.enemy_start_locations)
                elif self.enemy_structures.exists:
                    target = self.enemy_structures.closest_to(unit)
                else:
                    target = random.choice(self.expansion_locations_list)

                unit.attack(target)

            else:
                pass

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

    async def getTargetPosition(self, target: UnitTypeId, trainer: Unit) -> Point2:
        if target in STATIC_DEFENSE[self.race]:
            return self.townhalls.random.position.towards(self.game_info.map_center, -7)
        elif self.isStructure(target):
            if target in race_townhalls[self.race]:
                return await self.getNextExpansion()
            else:
                position = self.townhalls.closest_to(self.start_location).position
                return position.towards(self.game_info.map_center, 5)
        else:
            return trainer.position

    async def get_base_distance(self, base):

        distances_self = []
        for b in self.owned_expansions.keys():
            distance = await self.client.query_pathing(b, base) or b.distance_to(base)
            distances_self.append(distance)

        distances_enemy = []
        for b in self.enemy_start_locations:
            distance = await self.client.query_pathing(b, base) or b.distance_to(base)
            distances_enemy.append(distance)

        return max(distances_self) - min(distances_enemy)

    async def getNextExpansion(self) -> Point2:
        bases = [
            base
            for base, resources in self.expansion_locations_dict.items()
            if (
                not base in self.owned_expansions
                and not self.townhalls.closer_than(3, base).exists
                and resources.filter(lambda r : r.is_mineral_field or r.has_vespene).exists
            )
        ]
        bases = sorted(bases, key=lambda b : self.expansion_distances[b])
        if not bases:
            return None
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
        supplyBuffer += 3 * self.count(UnitTypeId.QUEEN, include_pending=False, include_planned=False)
        # supplyBuffer += 2 * self.count(UnitTypeId.BARRACKS)
        # supplyBuffer += 2 * self.count(UnitTypeId.FACTORY)
        # supplyBuffer += 2 * self.count(UnitTypeId.STARPORT)
        # supplyBuffer += 2 * self.count(UnitTypeId.GATEWAY)
        # supplyBuffer += 2 * self.count(UnitTypeId.WARPGATE)
        # supplyBuffer += 2 * self.count(UnitTypeId.ROBOTICSFACILITY)
        # supplyBuffer += 2 * self.count(UnitTypeId.STARGATE)
        return supplyBuffer

    def getSupplyPending(self) -> int:
        supplyPending = 0
        supplyPending += 8 * self.count_pending(SUPPLY[self.race])
        supplyPending += 8 * self.count_planned(SUPPLY[self.race])
        # supplyPending += sum(TOWNHALL_SUPPLY[self.race] * t.build_progress for t in self.townhalls.not_ready)
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

    def getTraining(self, unit: UnitTypeId) -> Units:
        trained_from = UNIT_TRAINED_FROM[unit]
        # trainers = self.units(trained_from) | self.structures(trained_from)
        trainers = (self.units | self.structures)
        abilities = TRAIN_ABILITIES[unit]
        trainers = trainers.filter(lambda t : any(o.ability.id in abilities for o in t.orders))
        return trainers

    def count(self, item, include_pending: bool = True, include_planned: bool = True) -> int:
        
        count = 0
        if type(item) is set:
            return sum(self.count(i) for i in item)
        elif type(item) is UnitTypeId:
            count += self.structures(item).amount
            count += self.units(item).amount
        elif type(item) is UpgradeId:
            count += 1 if item in self.state.upgrades else 0
        else:
            raise TypeError()
        if include_pending:
            count += self.count_pending(item)
        if include_planned:
            count += self.count_planned(item)
        return count

    def createCost(self, unit: UnitTypeId):
        cost = self.calculate_cost(unit)
        food = self.calculate_supply_cost(unit)
        return Cost(cost.minerals, cost.vespene, food)

    def createCost(self, upgrade: UpgradeId):
        cost = self.calculate_cost(upgrade)
        return Cost(cost.minerals, cost.vespene, 0)

    def unitValue(self, unit: UnitTypeId) -> int:
        value = self.calculate_unit_value(unit)
        return value.minerals + 2 * value.vespene

    def assignWorker(self):

        gasActual = sum((g.assigned_harvesters for g in self.gas_buildings))

        exclude = { o.unit.tag for o in self.macroObjectives if o.unit }

        worker = None
        target = None

        # if self.workers.idle.exists and self.townhalls.ready.exists:
        #     worker = self.workers.idle.random
        #     townhall = self.townhalls.ready.random
        #     minerals = self.mineral_field.closest_to(townhall)
        #     target = minerals

        workers_idle = self.workers.idle
        # workers_idle = workers_idle.filter(lambda w : not w.is_gathering and not w.is_returning)
        workers_idle = workers_idle.tags_not_in(exclude)

        if workers_idle.exists:
            worker = workers_idle.random

        if worker is None:
            for gas in self.gas_buildings.ready:
                workers = self.workers.tags_not_in(exclude).filter(lambda w : w.order_target == gas.tag)
                if workers.exists and (0 < gas.surplus_harvesters or self.gasTarget + 1 < gasActual):
                    worker = workers.furthest_to(gas)
                elif gas.surplus_harvesters < 0 and gasActual + 1 <= self.gasTarget:
                    target = gas

        if worker is None:
            for townhall in self.townhalls.ready:
                if 0 < townhall.surplus_harvesters or target is not None:
                    workers = self.workers.tags_not_in(exclude).closer_than(5, townhall)
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
                    break
                    
        # if target is None:
        #     for gas in self.gas_buildings.ready:
        #         if gas.surplus_harvesters < 0:
        #             target = gas
        #             break

        if target is None:
            return

        if worker.is_carrying_resource:
            worker.return_resource()
            worker.gather(target, queue=True)
        else:
            worker.gather(target)

    def canAffordWithReserve(self, cost: Cost, reserve: Cost) -> bool:
        if 0 < cost.minerals and self.minerals < reserve.minerals + cost.minerals:
            return False
        elif 0 < cost.vespene and self.vespene < reserve.vespene + cost.vespene:
            return False
        elif 0 < cost.food and self.supply_left < reserve.food + cost.food:
            return False
        else:
            return True

    def getMaxWorkers(self) -> int:
        workers = 0
        workers += sum((h.ideal_harvesters if h.build_progress == 1 else 16 * h.build_progress for h in self.townhalls))
        workers += sum((g.ideal_harvesters if g.build_progress == 1 else 3 * g.build_progress for g in self.gas_buildings))
        # for loc in self.owned_expansions.keys():
        #     base = self.expansion_locations_dict[loc]
        #     minerals = base.filter(lambda m : m.is_mineral_field)
        #     workers += 2 * minerals.amount
        # geysers = self.gas_buildings.filter(lambda g : g.has_vespene)
        # workers += 3 * geysers.amount
        # print(workers)
        return int(workers)

    def createCost(self, item: Union[UnitTypeId, UpgradeId, AbilityId]) -> Cost:
        minerals = 0
        vespene = 0
        food = 0
        if item is not None:
            cost = self.calculate_cost(item)
            minerals = cost.minerals
            vespene = cost.vespene
        if item in UnitTypeId:
            food = int(self.calculate_supply_cost(item))
        return Cost(minerals, vespene, food)

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