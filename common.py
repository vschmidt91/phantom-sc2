
from time import process_time
from numpy.core.fromnumeric import sort
from numpy.lib.shape_base import expand_dims
from constants import CIVILIANS, REQUIREMENTS, STATIC_DEFENSE, SUPPLY, SUPPLY_PROVIDED, TOWNHALL, TRAIN_ABILITIES, UNIT_BY_TRAIN_ABILITY, UPGRADE_BY_RESEARCH_ABILITY
from macro_target import MacroTarget
from cost import Cost
from collections import Counter, defaultdict
from itertools import chain, count

import math
import random
from typing import Iterable, Optional, Tuple, Union, Coroutine, Set, List, Callable
from numpy.lib.function_base import insert
from s2clientprotocol.error_pb2 import CantAddMoreCharges, Error
from sc2 import unit
from sc2 import position
from sc2.game_state import Common

from utils import get_requirements, armyValue, unitPriority, canAttack, center, dot, unitValue, withEquivalents
from constants import CHANGELINGS
from quotes import QUOTES

import numpy as np
import json
from sc2.position import Point2, Point3

from sc2 import Race, BotAI
from sc2.constants import ALL_GAS, SPEED_INCREASE_ON_CREEP_DICT
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

class PlacementNotFound(Exception):
    pass

class CommonAI(BotAI):

    def __init__(self, game_step: int = 1, debug: bool = False):

        self.game_step = game_step
        self.debug = debug

        # self.raw_affects_selection = True
        self.gas_target = 0
        self.macro_targets = list()
        self.units_by_type = defaultdict(lambda:[])
        self.pending_by_type = defaultdict(lambda:[])
        self.planned_by_type = defaultdict(lambda:[])
        self.units_by_tag = dict()

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

    async def on_step(self, iteration: int):

        # if self.state.effects:
        #     print(self.state.effects)

        if iteration == 0:
            quote = random.choice(QUOTES)
            await self.client.chat_send(quote, False)

        if self.debug:

            font_color = (255, 255, 255)
            font_size = 12

            for i, target in enumerate(self.macro_targets):

                positions = []

                if not target.target:
                    pass
                elif isinstance(target.target, Unit):
                    positions.append(target.target)
                elif isinstance(target.target, Point3):
                    positions.append(target.target)
                elif isinstance(target.target, Point2):
                    z = self.get_terrain_z_height(target.target)
                    positions.append(Point3((target.target.x, target.target.y, z)))

                if target.unit:
                    unit = self.units_by_tag.get(target.unit)
                    if unit:
                        positions.append(unit)

                text = f"{str(i+1)} {str(target.item.name)}"

                for position in positions:
                    self.client.debug_text_world(
                        text,
                        position,
                        color=font_color,
                        size=font_size)

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

        self.units_by_tag.clear()
        self.units_by_type.clear()
        self.pending_by_type.clear()
        self.planned_by_type.clear()

        for unit in self.all_own_units:
            self.units_by_tag[unit.tag] = unit
            if unit.is_ready:
                self.units_by_type[unit.type_id].append(unit)
            else:
                self.pending_by_type[unit.type_id].append(unit)
            for order in unit.orders:
                ability = order.ability.exact_id
                training = UNIT_BY_TRAIN_ABILITY.get(ability) or UPGRADE_BY_RESEARCH_ABILITY.get(ability)
                if training:
                    self.pending_by_type[training].append(unit)
        for upgrade in self.state.upgrades:
            self.units_by_type[upgrade].append(True)

        # self.table_actual.update(u.type_id for u in self.all_own_units.ready)
        # self.table_actual.update(self.state.upgrades)

        # self.table_pending.update(u.type_id for u in self.all_own_units.not_ready)
        # self.table_pending.update(
        #     UNIT_BY_TRAIN_ABILITY.get(o.ability.exact_id) or UPGRADE_BY_RESEARCH_ABILITY.get(o.ability.exact_id)
        #     for u in self.all_own_units
        #     for o in u.orders
        # )

        for target in self.macro_targets:
            self.planned_by_type[target.item].append(target)
        # self.table_planned.update(o.item for o in self.macro_targets)


    def count(
        self,
        item: Union[UnitTypeId, UpgradeId],
        include_pending: bool = True,
        include_planned: bool = True,
        include_actual: bool = True) -> int:
        
        sum = 0
        if include_actual:
            if item == race_worker[self.race]:
                # fix worker count (so that it includes workers in gas buildings)
                sum += self.supply_used - self.supply_army - len(self.pending_by_type[item])
            else:
                sum += len(self.units_by_type[item])
        if include_pending:
            sum += len(self.pending_by_type[item])
        if include_planned:
            sum += len(self.planned_by_type[item])

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

    async def time_to_reach(self, unit, target):
        if isinstance(target, Unit):
            position = target.position
        elif isinstance(target, Point2):
            position = target
        else:
            raise TypeError()
        path = await self.client.query_pathing(unit, position)
        if not path:
            path = unit.position.distance_to(position)
        if not unit.movement_speed:
            raise Error()
        return path / unit.movement_speed

    def get_requirements(self, item):
        requirements = REQUIREMENTS[item]
        requirements.difference_update(REQUIREMENTS_EXCLUDE)
        for requirement in requirements:
            if not self.count(requirement):
                yield requirement

    def add_macro_target(self, target: MacroTarget):
        self.macro_targets.append(target)
        self.planned_by_type[target.item].append(target.unit)

    async def macro(self):

        reserve = Cost(0, 0, 0)
        exclude = { o.unit for o in self.macro_targets }
        macro_targets_new = list(self.macro_targets)

        income_minerals, income_vespene = self.estimate_income()

        for objective in self.macro_targets:

            if not objective.cost:
                objective.cost = self.getCost(objective.item)

            can_afford = self.canAffordWithReserve(objective.cost, reserve)

            if objective.unit:
                unit = self.units_by_tag.get(objective.unit)
            else:
                unit, objective.ability = self.findTrainer(objective.item, exclude=exclude)

            if unit is None:
                continue

            objective.unit = unit.tag
            exclude.add(objective.unit)

            if objective.target is None:
                try:
                    objective.target = await self.get_target(unit, objective)
                except PlacementNotFound as p: 
                    continue

            requirement_missing = False
            for requirement in REQUIREMENTS[objective.item]:
                if not self.count(requirement, include_pending=False, include_planned=False):
                    requirement_missing = True
                    break

            if requirement_missing:
                continue

            if not objective.ability["ability"] in await self.get_available_abilities(unit, ignore_resource_requirements=True):
                continue

            reserve += objective.cost

            if (
                objective.target is not None
                and not unit.is_moving
                and unit.movement_speed
            ):
            
                time = await self.time_to_reach(unit, objective.target)
                
                minerals_needed = reserve.minerals - self.minerals
                vespene_needed = reserve.vespene - self.vespene
                time_minerals = minerals_needed / max(1, income_minerals)
                time_vespene = vespene_needed / max(1, income_vespene)
                time_to_harvest =  max(0, time_minerals, time_vespene)

                if time_to_harvest < time:
                    
                    if type(objective.target) is Unit:
                        move_to = objective.target.position
                    else:
                        move_to = objective.target

                    if unit.is_carrying_resource:
                        unit.return_resource()
                        unit.move(move_to, queue=True)
                    else:
                        unit.move(move_to)

            if not can_afford:
                continue
            
            abilities = await self.get_available_abilities(unit)
            if not objective.ability["ability"] in abilities:
                print("ability with cost failed:" + str(objective))
                raise Error()

            queue = False
            if unit.is_carrying_resource:
                unit.return_resource()
                queue = True

            if not unit(objective.ability["ability"], target=objective.target, queue=queue):
                print("objective failed:" + str(objective))
                raise Error()

            # self.pending.update((objective.item,))

            self.pending_by_type[objective.item].append(objective.unit)

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

    async def get_target(self, unit: Unit, objective: MacroTarget) -> Coroutine[any, any, Union[Unit, Point2]]:
        if objective.item in ALL_GAS:
            geysers = [
                g
                for g in self.get_owned_geysers()
                if not any(e.position == g.position for e in self.gas_buildings)
            ]
            if not geysers:
                raise PlacementNotFound()
            # return sorted(geysers, key=lambda g:g.tag)[0]
            return random.choice(geysers)
        elif "requires_placement_position" in objective.ability:
            position = await self.get_target_position(objective.item, unit)
            withAddon = objective in { UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT }
            if objective.item == TOWNHALL[self.race]:
                max_distance = 0
            else:
                max_distance = 8
            position = await self.find_placement(objective.ability["ability"], position, max_distance=max_distance, placement_step=1, addon_place=withAddon)
            if position is None:
                raise PlacementNotFound()
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

    def findTrainer(self, item: Union[UnitTypeId, UpgradeId], exclude: Set[int]) -> Coroutine[any, any, Tuple[Unit, any]]:

        if type(item) is UnitTypeId:
            trainer_types = UNIT_TRAINED_FROM[item]
        elif type(item) is UpgradeId:
            trainer_types = withEquivalents(UPGRADE_RESEARCHED_FROM[item])

        # trainers = self.structures(trainerTypes) | self.units(trainerTypes)
        # trainers = trainers.ready
        # trainers = trainers.tags_not_in(exclude)
        # trainers = trainers.filter(lambda t: self.hasCapacity(t))

        trainers = (
            trainer
            for trainer_type in trainer_types
            for trainer in self.units_by_type[trainer_type]
            if (
                trainer.is_ready
                and not trainer.tag in exclude
                and self.has_capacity(trainer)
            )
        )
            
        for trainer in trainers:

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

        friends = list(self.enumerate_army())

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

                friends_rating = sum(unitValue(f) / max(8, target.distance_to(f)) for f in friends)
                enemies_rating = sum(unitValue(e) / max(8, unit.distance_to(e)) for e in enemies)

                distance_bias = 50

                advantage = 1
                advantage_value = friends_rating / max(1, enemies_rating)
                advantage_defender = max(1, (distance_bias + target.distance_to(enemyBaseCenter)) / (distance_bias + target.distance_to(baseCenter)))
                
                advantage_creep = 1
                creep_bonus = SPEED_INCREASE_ON_CREEP_DICT.get(unit.type_id)
                if creep_bonus and self.state.creep.is_empty(unit.position.rounded):
                    advantage_creep = 1 / creep_bonus

                advantage *= advantage_value
                advantage *= advantage_defender
                advantage *= advantage_creep
                advantage_threshold = 1

                if advantage < .5 * advantage_threshold:

                    if not unit.is_moving:
                        unit.move(unit.position.towards(target, -12))

                elif advantage < 1 * advantage_threshold:

                    if unit.weapon_cooldown:

                        if unit.is_attacking:
                            unit.move(unit.position.towards(target, -15))

                    elif not unit.is_attacking:
                        unit.attack(target.position)
                    
                elif advantage < 2 * advantage_threshold:

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
                    unit.attack(self.destructables.closest_to(unit))

            elif not unit.is_attacking:

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
            if townhalls.exists:
                i = self.count(target) - 1
                return townhalls[i].position.towards(self.game_info.map_center, -5)
            else:
                return None
        elif self.isStructure(target):
            if target in race_townhalls[self.race]:
                return await self.getNextExpansion()
            elif self.townhalls.exists:
                position = self.townhalls.closest_to(self.start_location).position
                return position.towards(self.game_info.map_center, 5)
            else:
                return self.start_location
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

    def has_capacity(self, unit: Unit) -> bool:
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

    def get_supply_buffer(self) -> int:

        supplyBuffer = 4

        # supplyBuffer += sum(
        #     target.cost.food
        #     for target in self.macro_targets
        #     if target.cost
        # )

        supplyBuffer += 1 * self.townhalls.amount
        # supplyBuffer += 2 * self.larva.amount
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

        supply_have = self.count(SUPPLY[self.race], include_pending=False, include_planned=False)
        if self.supply_cap == 200:
            return supply_have

        supply_pending = sum(
            provided * self.count(unit)
            for unit, provided in SUPPLY_PROVIDED.items()
        )
            
        supply_buffer = self.get_supply_buffer()
        supplyNeeded = 1 + math.floor((supply_buffer - self.supply_left - supply_pending) / 8)

        return supply_have + supplyNeeded

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

    def enumerate_army(self):
        for unit in self.units:
            if not unit.type_id in CIVILIANS:
                yield unit

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

        exclude = { o.unit for o in self.macro_targets if o.unit }

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
            for gas in self.gas_buildings.ready:
                if gas.surplus_harvesters < 0:
                    target = gas
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