
from collections import defaultdict
from enum import Enum
from functools import reduce
import math
import random
from typing import Iterable, Optional, Tuple, Union, Coroutine, Set, List, Callable, Dict
import numpy as np
from s2clientprotocol.common_pb2 import Point
from s2clientprotocol.error_pb2 import Error

from sc2.game_state import ActionRawUnitCommand

from sc2.position import Point2, Point3
from sc2.bot_ai import BotAI
from sc2.constants import SPEED_INCREASE_ON_CREEP_DICT, IS_STRUCTURE
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.ids.upgrade_id import UpgradeId
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.unit_research_abilities import RESEARCH_INFO
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.dicts.unit_tech_alias import UNIT_TECH_ALIAS
from sc2.data import Result, race_townhalls, race_worker
from sc2.unit import Unit
from sc2.units import Units

from .resources.vespene_geyser import VespeneGeyser
from .resources.base import Base
from .resources.mineral_patch import MineralPatch
from .observation import Observation
from .resources.resource import Resource
from .resources.resource_group import ResourceGroup
from .constants import WORKERS, CHANGELINGS, REQUIREMENTS_KEYS, WITH_TECH_EQUIVALENTS, CIVILIANS, GAS_BY_RACE, REQUIREMENTS, REQUIREMENTS_EXCLUDE, STATIC_DEFENSE, SUPPLY, SUPPLY_PROVIDED, TOWNHALL, TRAIN_ABILITIES, UNIT_BY_TRAIN_ABILITY, UPGRADE_BY_RESEARCH_ABILITY
from .macro_plan import MacroPlan
from .cost import Cost
from .utils import can_attack, get_requirements, armyValue, unitPriority, canAttack, center, dot, unitValue

RESOURCE_DISTANCE_THRESHOLD = 10

class PlacementNotFound(Exception):
    pass

class PerformanceMode(Enum):
    DEFAULT = 1
    HIGH_PERFORMANCE = 2

class CommonAI(BotAI):

    def __init__(self,
        game_step: int = 1,
        debug: bool = False,
        performance: PerformanceMode = PerformanceMode.DEFAULT,
        version_path: str = './version.txt',
    ):

        self.tags: List[str] = []

        with open(version_path, 'r') as file:
            version = file.readline()
            self.tags.append(version)

        self.game_step = game_step
        self.performance = performance
        self.debug = debug
        self.raw_affects_selection = True
        self.gas_target = 0
        self.greet_enabled = True
        self.macro_plans = list()
        self.observation: Observation = Observation()
        self.worker_split: Dict[int, int] = None
        self.cost: Dict[Union[UnitTypeId, UpgradeId], Cost] = dict()
        self.bases: ResourceGroup[Base] = None
        self.base_distance_matrix: Dict[Point2, Dict[Point2, float]] = dict()

    def destroy_destructables(self):
        return True

    async def on_before_start(self):
        self.client.game_step = self.game_step
        self.cost = dict()
        for unit in  UnitTypeId:
            try:
                cost = self.calculate_cost(unit)
                food = int(self.calculate_supply_cost(unit))
                self.cost[unit] = Cost(cost.minerals, cost.vespene, food)
            except:
                pass
        for upgrade in UpgradeId:
            try:
                cost = self.calculate_cost(upgrade)
                self.cost[upgrade] = Cost(cost.minerals, cost.vespene, 0)
            except:
                pass

    async def on_start(self):
        await self.initialize_bases()

    async def on_step(self, iteration: int):

        if 1 < self.time and self.greet_enabled:
            for tag in self.tags:
                await self.client.chat_send('Tag:' + tag, True)
            self.greet_enabled = False
        if self.debug:
            self.draw_debug()

        for error in self.state.action_errors:
            print(error)

    async def on_end(self, game_result: Result):
        pass

    async def on_building_construction_started(self, unit: Unit):
        pass

    async def on_building_construction_complete(self, unit: Unit):
        self.observation.actual_by_type[unit.type_id].add(unit.tag)
        if unit.type_id in race_townhalls[self.race]:
            base = next((b for b in self.bases if b.position == unit.position), None)
            if base:
                base.townhall = unit.tag
        if unit.type_id in race_townhalls[self.race]:
            if self.mineral_field.exists:
                unit.smart(self.mineral_field.closest_to(unit))
        pass

    async def on_enemy_unit_entered_vision(self, unit: Unit):
        pass

    async def on_enemy_unit_left_vision(self, unit_tag: int):
        pass

    async def on_unit_created(self, unit: Unit):
        self.observation.actual_by_type[unit.type_id].add(unit.tag)
        if unit.type_id == race_worker[self.race]:
            if self.time == 0:
                return
            base = min(self.bases, key = lambda b : unit.distance_to(b.position))
            base.try_add(unit.tag)
        pass

    async def on_unit_destroyed(self, unit_tag: int):
        unit = self.observation.unit_by_tag.get(unit_tag)
        if unit:
            self.observation.actual_by_type[unit.type_id].difference_update((unit.tag,))
          
        base = next((b for b in self.bases if b.townhall == unit_tag), None)
        if base:
            base.townhall = None
        pass

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float):
        if (unit.is_structure and not unit.is_ready):
            if self.performance == PerformanceMode.DEFAULT:
                potential_damage = 0
                for enemy in self.all_enemy_units:
                    damage, speed, range = enemy.calculate_damage_vs_target(unit)
                    if  unit.distance_to(enemy) < unit.radius + range + enemy.radius:
                        potential_damage += damage
                if unit.health + unit.shield <= potential_damage:
                    unit(AbilityId.CANCEL)
            else:
                if unit.shield_health_percentage < 0.1:
                    unit(AbilityId.CANCEL)
        pass
        
    async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId):
        self.observation.actual_by_type[previous_type].difference_update((unit.tag,))
        self.observation.actual_by_type[unit.type_id].add(unit.tag)
        pass

    async def on_upgrade_complete(self, upgrade: UpgradeId):
        self.observation.add_upgrade(upgrade)
        pass

    def update_observation(self):
        self.observation.clear()
        for unit in self.all_own_units:
            self.observation.add_unit(unit)
        for resource in self.resources:
            self.observation.add_resource(resource)
        for destructable in self.destructables:
            self.observation.add_destructable(destructable)
        worker_type = race_worker[self.race]
        worker_pending = self.observation.count(worker_type, include_actual=False, include_pending=False, include_planned=False)
        self.observation.worker_supply_fixed = self.supply_used - self.supply_army - worker_pending

    @property
    def gas_harvesters(self) -> Iterable[int]:
        for base in self.bases:
            for gas in base.vespene_geysers:
                for harvester in gas.harvesters:
                    yield harvester

    @property
    def gas_harvester_count(self) -> int:
        return sum(1 for _ in self.gas_harvesters)

    def transfer_to_and_from_gas(self):

        while self.gas_harvester_count + 1 <= self.gas_target:
            minerals_from = max(
                (b.mineral_patches for b in self.bases if 0 < b.mineral_patches.harvester_count),
                key = lambda m : m.harvester_balance,
                default = None
            )
            gas_to = min(
                (b.vespene_geysers for b in self.bases if b.vespene_geysers.harvester_balance < 0),
                key = lambda g : g.harvester_balance,
                default = None
            )
            if minerals_from and gas_to and minerals_from.try_transfer_to(gas_to):
                continue
            break

        while self.gas_target <= self.gas_harvester_count - 1:
            gas_from = max(
                (b.vespene_geysers for b in self.bases if 0 < b.vespene_geysers.harvester_count),
                key = lambda g : g.harvester_balance,
                default = None
            )
            minerals_to = min(
                (b.mineral_patches for b in self.bases if 0 < b.mineral_patches.remaining),
                key = lambda m : m.harvester_balance,
                default = None
            )
            if gas_from and minerals_to and gas_from.try_transfer_to(minerals_to):
                continue
            break

    def update_bases(self):

        self.bases.update(self.observation)

        # if we are oversaturated, enable long distance mining
        # self.bases.balance_aggressively = 0 < self.bases.harvester_balance

    async def initialize_bases(self):

        num_attempts = 32
        max_sigma = 5
        self.base_distance_matrix = dict()
        for a in self.expansion_locations_list:
            self.base_distance_matrix[a] = dict()
            for b in self.expansion_locations_list:
                path = None
                for i in range(num_attempts):
                    sigma = max_sigma * i / num_attempts
                    sa = Point2(np.random.normal(a, sigma))
                    sb = Point2(np.random.normal(b, sigma))
                    path = await self.client.query_pathing(sa, sb)
                    if path:
                        break
                if not path:
                    path = a.distance_to(b)
                self.base_distance_matrix[a][b] = path

        expansions = [self.start_location]
        while len(expansions) < len(self.expansion_locations_list):
            expansion = min(
                (e for e in self.expansion_locations_list if e not in expansions),
                key=lambda e: max(self.base_distance_matrix[e][f] for f in expansions) - min(self.base_distance_matrix[e][f] for f in self.enemy_start_locations)
            )
            expansions.append(expansion)

        bases = []
        for townhall_position in expansions:
            resources = self.expansion_locations_dict[townhall_position]
            minerals = (m.position for m in resources.mineral_field)
            gasses = (g.position for g in resources.vespene_geyser)
            base = Base(townhall_position, minerals, gasses)
            bases.append(base)
        self.bases = ResourceGroup(bases)
        self.bases.items[0].mineral_patches.do_worker_split(set(self.workers))

    def draw_debug(self):

        font_color = (255, 255, 255)
        font_size = 12

        for i, target in enumerate(self.macro_plans):

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
                unit = self.observation.unit_by_tag.get(target.unit)
                if unit:
                    positions.append(unit)

            text = f"{str(i+1)} {str(target.item.name)}"

            for position in positions:
                self.client.debug_text_world(
                    text,
                    position,
                    color=font_color,
                    size=font_size)

    @property
    def income(self):
        income_minerals = sum(base.mineral_patches.income for base in self.bases)
        income_vespene = sum(base.vespene_geysers.income for base in self.bases)
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
            if self.debug:
                raise Exception()
            else:
                return 0
        return path / unit.movement_speed

    def add_macro_plan(self, plan: MacroPlan):
        self.macro_plans.append(plan)
        self.observation.add_plan(plan)

    def get_missing_requirements(self, item: Union[UnitTypeId, UpgradeId], **kwargs) -> Set[Union[UnitTypeId, UpgradeId]]:

        if item not in REQUIREMENTS_KEYS:
            return set()

        requirements = list()

        if type(item) is UnitTypeId:
            trainers = UNIT_TRAINED_FROM[item]
            trainer = min(trainers, key=lambda v:v.value)
            requirements.append(trainer)
            info = TRAIN_INFO[trainer][item]
        elif type(item) is UpgradeId:
            researcher = UPGRADE_RESEARCHED_FROM[item]
            requirements.append(researcher)
            info = RESEARCH_INFO[researcher][item]
        else:
            raise TypeError()

        requirements.append(info.get('required_building'))
        requirements.append(info.get('required_upgrade'))
        
        missing = set()
        i = 0
        while i < len(requirements):
            requirement = requirements[i]
            i += 1
            if not requirement:
                continue
            if type(requirement) is UnitTypeId:
                equivalents = WITH_TECH_EQUIVALENTS[requirement]
            elif type(requirement) is UpgradeId:
                equivalents = { requirement }
            else:
                raise TypeError()
            if any(self.observation.count(e, **kwargs) for e in equivalents):
                continue
            missing.add(requirement)
            requirements.extend(self.get_missing_requirements(requirement, **kwargs))

        return missing

    async def macro(self):

        reserve = Cost(0, 0, 0)
        exclude = { o.unit for o in self.macro_plans }
        took_action = False
        income_minerals, income_vespene = self.income
        self.macro_plans.sort(key = lambda t : t.priority, reverse=True)

        i = 0
        while i < len(self.macro_plans):

            plan = self.macro_plans[i]
            i += 1

            cost = self.cost[plan.item]
            can_afford = self.can_afford_with_reserve(cost, reserve)
            reserve += cost

            unit = None
            if plan.unit:
                unit = self.observation.unit_by_tag.get(plan.unit)
            if not unit:
                unit, plan.ability = self.search_trainer(plan.item, exclude=exclude)
            if not unit:
                continue

            if unit.type_id != UnitTypeId.LARVA:
                plan.unit = unit.tag
            exclude.add(plan.unit)

            if plan.target is None:
                try:
                    plan.target = await self.get_target(unit, plan)
                except PlacementNotFound as p: 
                    continue

            if any(self.get_missing_requirements(plan.item, include_pending=False, include_planned=False)):
                continue

            if (
                plan.target
                and not unit.is_moving
                and unit.movement_speed
            ):
            
                time = await self.time_to_reach(unit, plan.target)
                
                minerals_needed = reserve.minerals - self.minerals
                vespene_needed = reserve.vespene - self.vespene
                time_minerals = minerals_needed / max(1, income_minerals)
                time_vespene = vespene_needed / max(1, income_vespene)
                time_to_harvest =  max(0, time_minerals, time_vespene)

                if time_to_harvest < time:
                    
                    if type(plan.target) is Unit:
                        move_to = plan.target
                    else:
                        move_to = plan.target

                    if unit.is_carrying_resource:
                        unit.return_resource()
                        unit.move(move_to, queue=True)
                    else:
                        unit.move(move_to)

                    if unit.type_id == race_worker[self.race]:
                        self.bases.try_remove(unit.tag)

            if not can_afford:
                continue

            if unit.type_id == race_worker[self.race]:
                self.bases.try_remove(unit.tag)

            if self.is_structure(plan.item) and isinstance(plan.target, Point2):
                if not await self.can_place_single(plan.item, plan.target):
                    plan.target = None
                    continue

            if took_action:
                continue

            queue = False
            if unit.is_carrying_resource:
                unit.return_resource()
                queue = True

            if plan.item == UnitTypeId.RAVAGER:
                queue = queue

            if not unit(plan.ability["ability"], target=plan.target, queue=queue):
                if self.debug:
                    print("objective failed:" + str(plan))
                    raise Exception()

            took_action = True

            self.observation.remove_plan(plan)
            self.observation.add_pending(plan.item, unit)

            i -= 1
            self.macro_plans.pop(i)


    def get_owned_geysers(self):
        for base in self.bases:
            if not base.townhall:
                continue
            for gas in base.vespene_geysers:
                geyser = self.observation.resource_by_position[gas.position]
                yield geyser

    async def get_target(self, unit: Unit, objective: MacroPlan) -> Coroutine[any, any, Union[Unit, Point2]]:
        gas_type = GAS_BY_RACE[self.race]
        if objective.item == gas_type:
            exclude_positions = {
                geyser.position
                for geyser in self.gas_buildings
            }
            exclude_tags = {
                order.target
                for trainer in self.observation.pending_by_type[gas_type]
                for order in trainer.orders
                if isinstance(order.target, int)
            }
            exclude_tags.update({
                step.target.tag
                for step in self.observation.planned_by_type[gas_type]
                if step.target
            })
            geysers = [
                geyser
                for geyser in self.get_owned_geysers()
                if (
                    geyser.position not in exclude_positions
                    and geyser.tag not in exclude_tags
                )
            ]
            if not any(geysers):
                raise PlacementNotFound()
            else:
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

    def search_trainer(self, item: Union[UnitTypeId, UpgradeId], exclude: Set[int]) -> Tuple[Unit, any]:

        if type(item) is UnitTypeId:
            trainer_types = {
                equivalent
                for trainer in UNIT_TRAINED_FROM[item]
                for equivalent in WITH_TECH_EQUIVALENTS[trainer]
            }
        elif type(item) is UpgradeId:
            trainer_types = WITH_TECH_EQUIVALENTS[UPGRADE_RESEARCHED_FROM[item]]

        trainers = (
            self.observation.unit_by_tag.get(trainer_tag)
            for trainer_type in trainer_types
            for trainer_tag in self.observation.actual_by_type[trainer_type]
        )
            
        for trainer in trainers:

            if not trainer:
                continue

            if not trainer.is_ready:
                continue

            if trainer.tag in exclude:
                continue

            if not self.has_capacity(trainer):
                continue

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
                
            return trainer, ability

        return None, None

    async def micro(self):

        friends = list(self.enumerate_army())

        enemies = self.all_enemy_units
        if self.destroy_destructables():
            enemies += self.observation.destructables
        enemies = list(enemies)

        for unit in friends:

            def target_priority(target: Unit) -> float:
                if target.is_hallucination:
                    return 0
                if target.type_id in CHANGELINGS:
                    return 0
                if not can_attack(unit, target) and not unit.is_detector:
                    return 0
                priority = 1
                priority *= 10 + target.calculate_dps_vs_target(unit)
                priority /= 100 + target.shield + target.health
                priority /= 10 + unit.distance_to(target)
                priority /= 30 + unit.distance_to(self.start_location)
                priority /= 3 if target.is_structure else 1
                priority *= 3 if target.type_id in WORKERS else 1
                priority /= 3 if target.type_id in CIVILIANS else 1
                priority /= 3 if not target.is_enemy else 1
                if unit.is_detector:
                    priority *= 10 if target.is_cloaked else 1
                    priority *= 10 if not target.is_revealed else 1
                return priority

            target = max(enemies, key=target_priority, default=None)
            if target and 0 < target_priority(target):

                if target.is_enemy:
                    attack_target = target.position
                else:
                    attack_target = target

                friends_rating = sum(unitValue(f) / max(8, target.distance_to(f)) for f in friends)
                enemies_rating = sum(unitValue(e) / max(8, unit.distance_to(e)) for e in enemies)

                distance_ref = self.game_info.map_size.length
                distance_to_base = min((unit.distance_to(t) for t in self.townhalls), default=0)

                advantage = 1
                advantage_value = friends_rating / max(1, enemies_rating)
                advantage_defender = distance_ref / (distance_ref + distance_to_base)
                
                advantage_creep = 1
                creep_bonus = SPEED_INCREASE_ON_CREEP_DICT.get(unit.type_id)
                if creep_bonus and self.state.creep.is_empty(unit.position.rounded):
                    advantage_creep = 1 / creep_bonus

                advantage *= advantage_value
                advantage *= advantage_defender
                advantage *= advantage_creep
                advantage_threshold = 1

                if advantage < advantage_threshold / 3:

                    # FLEE
                    if not unit.is_moving:
                        unit.move(unit.position.towards(target, -12))

                elif advantage < advantage_threshold:

                    # RETREAT
                    if unit.weapon_cooldown and unit.target_in_range(target, unit.distance_to_weapon_ready):
                        unit.move(unit.position.towards(target, -12))
                    elif unit.target_in_range(target):
                        unit.attack(target)
                    else:
                        unit.attack(attack_target)
                    
                elif advantage < advantage_threshold * 3:

                    # FIGHT
                    if unit.target_in_range(target):
                        unit.attack(target)
                    else:
                        unit.attack(attack_target)

                else:

                    # PURSUE
                    distance = unit.position.distance_to(target.position) - unit.radius - target.radius
                    if unit.weapon_cooldown and 1 < distance:
                        unit.move(target.position)
                    elif unit.target_in_range(target):
                        unit.attack(target)
                    else:
                        unit.attack(attack_target)

            elif not unit.is_attacking:

                if self.time < 8 * 60:
                    target = random.choice(self.enemy_start_locations)
                else:
                    target = random.choice(self.expansion_locations_list)

                unit.attack(target)

    async def get_target_position(self, target: UnitTypeId, trainer: Unit) -> Point2:
        if target in STATIC_DEFENSE[self.race]:
            townhalls = self.townhalls.ready.sorted_by_distance_to(self.start_location)
            if townhalls.exists:
                i = (self.observation.count(target) - 1) % townhalls.amount
                return townhalls[i].position.towards(self.game_info.map_center, -5)
            else:
                return self.start_location
        elif self.is_structure(target):
            if target in race_townhalls[self.race]:
                for b in self.bases:
                    if b.townhall:
                        continue
                    if not await self.can_place_single(target, b.position):
                        continue
                    return b.position
                raise PlacementNotFound()
            elif self.townhalls.exists:
                position = self.townhalls.closest_to(self.start_location).position
                return position.towards(self.game_info.map_center, 5)
            else:
                raise PlacementNotFound()
        else:
            return trainer.position

    def has_capacity(self, unit: Unit) -> bool:
        if self.is_structure(unit.type_id):
            if unit.has_reactor:
                return len(unit.orders) < 2
            else:
                return unit.is_idle
        else:
            return True

    def is_structure(self, unit: UnitTypeId) -> bool:
        data = self.game_data.units.get(unit.value)
        if data is None:
            return False
        return IS_STRUCTURE in data.attributes

    def get_supply_buffer(self) -> int:
        buffer = 4
        buffer += 1 * self.townhalls.amount
        buffer += 3 * self.observation.count(UnitTypeId.QUEEN, include_pending=False, include_planned=False)
        return buffer

    def enumerate_army(self):
        for unit in self.units:
            if not unit.type_id in CIVILIANS:
                yield unit

    def can_afford_with_reserve(self, cost: Cost, reserve: Cost) -> bool:
        if 0 < cost.minerals and self.minerals < reserve.minerals + cost.minerals:
            return False
        elif 0 < cost.vespene and self.vespene < reserve.vespene + cost.vespene:
            return False
        elif 0 < cost.food and self.supply_left < reserve.food + cost.food:
            return False
        else:
            return True

    def get_max_harvester(self) -> int:
        workers = 0
        workers += sum((b.harvester_target for b in self.bases))
        workers += 16 * self.observation.count(UnitTypeId.HATCHERY, include_actual=False, include_planned=False)
        return workers

    def blocked_base(self, position: Point2) -> Optional[Point]:
        px, py = position
        radius = self.game_data.units[UnitTypeId.HATCHERY.value].footprint_radius
        for base in self.expansion_locations_list:
            bx, by = base
            if abs(px - bx) < radius:
                return base
            elif abs(py - by) < radius:
                return base
        return None