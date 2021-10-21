
from time import process_time
from numpy.core.fromnumeric import sort
from numpy.lib.shape_base import expand_dims
from constants import CIVILIANS, REQUIREMENTS, STATIC_DEFENSE, SUPPLY, TOWNHALL, TRAIN_ABILITIES, UNIT_BY_TRAIN_ABILITY, UPGRADE_BY_RESEARCH_ABILITY
from macro_target import MacroTarget
from cost import Cost
from collections import Counter
from itertools import chain

import math
import random
from typing import Iterable, Optional, Tuple, Union, Coroutine, Set, List, Callable
from numpy.lib.function_base import insert
from s2clientprotocol.error_pb2 import CantAddMoreCharges, Error
from sc2.game_state import Common

from utils import get_requirements, armyValue, unitPriority, canAttack, center, dot, unitValue, withEquivalents
from constants import CHANGELINGS

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

RESOURCE_DISTANCE_THRESHOLD = 10

REQUIREMENTS_EXCLUDE = {
    UnitTypeId.DRONE,
    UnitTypeId.LARVA,
    UnitTypeId.HATCHERY,
}

class CommonAI(BotAI):

    def __init__(self, game_step: int = 1):

        self.game_step = game_step

        try:
            with open('quotes.txt', 'r') as file:
                self.quotes = file.readlines()
        except:
            self.quotes = None

        self.raw_affects_selection = True
        self.gas_target = 0
        self.macro_targets = list()
        self.table_actual = Counter()
        self.table_pending = Counter()
        self.table_planned = Counter()

    async def on_before_start(self):
        self.client.game_step = self.game_step
        pass

    async def on_start(self):

        self.position_to_expansion = dict()
        for resource in self.resources:
            expansion = min(self.expansion_locations_list, key = lambda e : e.distance_to(resource))
            self.position_to_expansion[resource.position] = expansion

        self.expansion_distances = {
            b: await self.get_base_distance(b)
            for b in self.expansion_locations_list
        }

    async def  on_step(self, iteration: int):

        if iteration == 0:

            if self.quotes:
                quote = random.choice(self.quotes)
                await self.client.chat_send(quote, False)

        pass

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
        elif unit.type_id == UnitTypeId.CREEPTUMORBURROWED:
            unit(AbilityId.CANCEL)
        

    async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId):
        pass

    async def on_upgrade_complete(self, upgrade: UpgradeId):
        pass

    def update_tables(self):

        self.table_actual.clear()
        self.table_actual.update((u.type_id for u in self.all_own_units))
        self.table_actual.update(self.state.upgrades)

        self.table_pending.clear()
        self.table_pending.update((
            UNIT_BY_TRAIN_ABILITY.get(o.ability.exact_id) or UPGRADE_BY_RESEARCH_ABILITY.get(o.ability.exact_id)
            for u in self.all_own_units
            for o in u.orders
        ))

        self.table_planned.clear()
        self.table_planned.update((o.item for o in self.macro_targets))

        # fix worker count (so that it includes workers in gas buildings)
        worker_type = race_worker[self.race]
        worker_supply = self.supply_used - self.supply_army
        self.table_actual[worker_type] = worker_supply - self.table_pending[worker_type]

    def count(
        self,
        item: Union[UnitTypeId, UpgradeId],
        include_pending: bool = True,
        include_planned: bool = True,
        include_actual: bool = True) -> int:
        
        sum = 0
        if include_actual:
            sum += self.table_actual[item]
        if include_pending:
            sum += self.table_pending[item]
        if include_planned:
            sum += self.table_planned[item]
        return sum

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

    def get_requirements(self, item):
        requirements = REQUIREMENTS[item]
        requirements.difference_update(REQUIREMENTS_EXCLUDE)
        for requirement in requirements:
            if not self.count(requirement):
                yield requirement

    async def macro(self):

        reserve = Cost(0, 0, 0)
        macro_targets_new = list(self.macro_targets)

        for objective in self.macro_targets:

            if objective.cost is None:
                objective.cost = self.getCost(objective.item)

            if objective.unit is None:
                exclude = { o.unit.tag for o in macro_targets_new if o.unit }
                objective.unit, objective.ability = await self.findTrainer(objective.item, exclude=exclude)
            else:
                if any((o for o in macro_targets_new if o != objective and o.unit and o.unit.tag == objective.unit.tag)):
                    raise Error()
                unit_new = self.units.find_by_tag(objective.unit.tag) or self.structures.find_by_tag(objective.unit.tag)
                # if unit_new is None:
                #     raise Error()
                objective.unit = unit_new


            if objective.unit is None:
                # reserve += objective.cost
                continue

            if objective.target is None:
                try:
                    objective.target = await self.get_target(objective)
                except: 
                    continue

            # requiredBuilding = objective.ability.get("required_building", None)
            # if requiredBuilding is not None:
            #     requiredBuilding = withEquivalents(requiredBuilding)
            #     if not self.structures(requiredBuilding).ready.exists:
            #         reserve += objective.cost
            #         continue

            # requiredUpgrade = objective.ability.get("required_upgrade", None)
            # if requiredUpgrade is not None:
            #     if not requiredUpgrade in self.state.upgrades:
            #         reserve += objective.cost
            #         continue

            if not objective.ability["ability"] in await self.get_available_abilities(objective.unit, ignore_resource_requirements=True):
                # print("ability failed:" + str(objective))
                objective.unit = None
                objective.target = None
                reserve += objective.cost
                continue

            if (
                objective.target is not None
                and not objective.unit.is_moving
                and not objective.unit.is_returning
                and objective.unit.movement_speed
                and 1 < objective.unit.distance_to(objective.target)
            ):
                minerals_needed = objective.cost.minerals + reserve.minerals - self.minerals
                vespene_needed = objective.cost.vespene + reserve.vespene - self.vespene
                if (
                    self.time_to_harvest(minerals_needed, vespene_needed) < self.time_to_reach(objective.unit, objective.target)
                ):
                    
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
                reserve += objective.cost
                continue

            queue = False
            if objective.unit.is_carrying_resource:
                objective.unit.return_resource()
                queue = True

            if not objective.unit(objective.ability["ability"], target=objective.target, queue=queue):
                # print("objective failed:" + str(objective))
                # reserve += objective.cost
                objective.unit = None
                objective.target = None
                reserve += objective.cost
                continue

            # self.pending.update((objective.item,))

            macro_targets_new.remove(objective)
            break

        self.macro_targets = sorted(macro_targets_new, key=lambda o:-o.priority)

    def get_owned_geysers(self):
        if not self.townhalls.ready.exists:
            return
        for geyser in self.resources.vespene_geyser:
            townhall = self.townhalls.ready.closest_to(geyser)
            if geyser.distance_to(townhall) < RESOURCE_DISTANCE_THRESHOLD:
                yield geyser

    async def get_target(self, objective: MacroTarget) -> Coroutine[any, any, Union[Unit, Point2]]:
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
            position = await self.get_target_position(objective.item, objective.unit)
            withAddon = objective in { UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT }
            if objective.item == TOWNHALL[self.race]:
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
            trainerTypes = withEquivalents(UPGRADE_RESEARCHED_FROM[item])

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
                if order_unit:
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

            # requiredBuilding = ability.get("required_building", None)
            # if requiredBuilding is not None:
            #     requiredBuilding = withEquivalents(requiredBuilding)
            #     if not self.structures(requiredBuilding).ready.exists:
            #         continue

            # requiredUpgrade = ability.get("required_upgrade", None)
            # if requiredUpgrade is not None:
            #     if not requiredUpgrade in self.state.upgrades:
            #         continue

            # if ability["ability"] not in abilities:
            #     continue
                
            return trainer, ability

        return None, None

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

        # friends_rating = sum(self.unit_cost(f) for f in friends)
        # enemies_rating = sum(self.unit_cost(e) for e in enemies)

        for unit in friends:

            if enemies.exists:

                target = enemies.closest_to(unit)

                friends_rating = sum(unitValue(f) / max(1, target.distance_to(f)) for f in friends)
                enemies_rating = sum(unitValue(e) / max(1, unit.distance_to(e)) for e in enemies)

                distance_bias = 50

                advantage = 1
                advantage_value = friends_rating / max(1, enemies_rating)
                advantage_defender = (distance_bias + target.distance_to(enemyBaseCenter)) / (distance_bias + target.distance_to(baseCenter))
                advantage *= advantage_value
                advantage *= advantage_defender

                if advantage < .5:

                    if not unit.is_moving:

                        unit.move(unit.position.towards(target, -12))

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

                if unit.type_id == UnitTypeId.BANELING:
                    continue

                if not unit.is_attacking:
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

    async def get_target_position(self, target: UnitTypeId, trainer: Unit) -> Point2:
        if target in STATIC_DEFENSE[self.race]:
            townhalls = self.townhalls.ready.sorted_by_distance_to(self.start_location)
            i = self.count(target)
            return townhalls[i].position.towards(self.game_info.map_center, -5)
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
                not self.townhalls.closer_than(3, base).exists
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

        # mineral_field_to_position = dict()
        # expansion_to_mineral_fields = dict()
        # for mineral_field in self.resources.mineral_field:
        #     mineral_field_to_position[mineral_field.tag] = mineral_field.position
        #     expansion = self.position_to_expansion[mineral_field.position]
        #     expansion_to_mineral_fields.setdefault(expansion, list()).append(mineral_field)


        # expansion_to_townhall = dict()
        # for expansion in self.expansion_locations_list:
        #     townhall = self.townhalls.ready.closest_to(expansion)
        #     if expansion.distance_to(townhall) < RESOURCE_DISTANCE_THRESHOLD:
        #         expansion_to_townhall[expansion] = townhall

        gasActual = sum(g.assigned_harvesters for g in self.gas_buildings)

        exclude = { o.unit.tag for o in self.macro_targets if o.unit }

        worker = None
        target = None

        workers = self.workers.tags_not_in(exclude)
        if workers.idle.exists:
            worker = workers.idle.random

        if worker is None:
            for gas in self.gas_buildings.ready:
                workers_gas = workers.filter(lambda w : w.order_target == gas.tag)
                if workers_gas.exists and (0 < gas.surplus_harvesters or self.gas_target + 1 < gasActual):
                    worker = workers_gas.furthest_to(gas)
                elif gas.surplus_harvesters < 0 and gasActual + 1 <= self.gas_target:
                    target = gas

        if worker is None:

            # for w in workers:
            #     position = mineral_field_to_position.get(w.order_target)
            #     expansion = self.position_to_expansion.get(position)
            #     townhall = expansion_to_townhall.get(expansion)
            #     if (
            #         townhall is not None
            #         and (0 < townhall.surplus_harvesters or target)
            #     ):
            #         worker = w
            #         break

            for townhall in self.townhalls.ready:
                if 0 < townhall.surplus_harvesters or target is not None:
                    workers = self.workers.tags_not_in(exclude).closer_than(5, townhall)
                    if workers.exists:
                        worker = workers.random
                        break

        if worker is None:
            return

        if target is None:

            # for location, townhall in expansion_to_townhall.items():
            #     if townhall.surplus_harvesters < 0:
            #         target = expansion_to_mineral_fields[location][0]
            #         break

            for townhall in self.townhalls.ready:
                if townhall.surplus_harvesters < 0:
                    target = self.mineral_field.closest_to(townhall)
                    break

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
        workers += self.gas_target
        # workers += sum((g.ideal_harvesters if g.build_progress == 1 else 3 * g.build_progress for g in self.gas_buildings))

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