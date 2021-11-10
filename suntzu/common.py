
from collections import defaultdict
from enum import Enum
from functools import reduce
import math
import random
from typing import Iterable, Optional, Tuple, Union, Coroutine, Set, List, Callable, Dict
import numpy as np
from s2clientprotocol.raw_pb2 import Effect
from scipy import ndimage
from s2clientprotocol.common_pb2 import Point
from s2clientprotocol.error_pb2 import Error
from queue import Queue
import os

from sc2.game_state import ActionRawUnitCommand
from sc2.ids.effect_id import EffectId
from sc2 import game_info, game_state
from sc2.position import Point2, Point3
from sc2.bot_ai import BotAI
from sc2.constants import SPEED_INCREASE_ON_CREEP_DICT, IS_STRUCTURE
from sc2.ids.buff_id import BuffId
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

from .analysis.poisson_solver import solve_poisson, solve_poisson_full
from .resources.vespene_geyser import VespeneGeyser
from .resources.base import Base
from .resources.mineral_patch import MineralPatch
from .observation import Observation
from .resources.resource import Resource
from .resources.resource_group import ResourceGroup
from .constants import *
from .macro_plan import MacroPlan
from .cost import Cost
from .utils import *
from .corrosive_bile import CorrosiveBile
 
DODGE_EFFECTS = {
    # EffectId.THERMALLANCESFORWARD,
    EffectId.LURKERMP,
    # EffectId.NUKEPERSISTENT,
    # EffectId.RAVAGERCORROSIVEBILECP,
    EffectId.PSISTORMPERSISTENT,
}

DODGE_UNITS = {
    UnitTypeId.DISRUPTORPHASED,
    UnitTypeId.WIDOWMINEWEAPON,
    UnitTypeId.WIDOWMINEAIRWEAPON,
    UnitTypeId.NUKE,
}

class PlacementNotFound(Exception):
    pass

class PerformanceMode(Enum):
    DEFAULT = 1
    HIGH_PERFORMANCE = 2

class CommonAI(BotAI):

    def __init__(self,
        game_step: Optional[int] = None,
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
        self.greet_enabled = True
        self.macro_plans = list()
        self.composition: Dict[UnitTypeId, int] = dict()
        self.observation: Observation = Observation()
        self.worker_split: Dict[int, int] = None
        self.cost: Dict[Union[UnitTypeId, UpgradeId], Cost] = dict()
        self.bases: ResourceGroup[Base] = None
        self.enemy_positions: Optional[Dict[int, Point2]] = dict()
        self.corrosive_biles: List[CorrosiveBile] = list()
        self.heat_map = None
        self.heat_map_sum = 0
        self.heat_map_gradient = None

    def destroy_destructables(self):
        return True

    async def on_before_start(self):
        if self.game_step is not None:
            self.client.game_step = self.game_step
        self.cost = dict()
        for unit in UnitTypeId:
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
        self.townhalls[0](AbilityId.RALLY_WORKERS, target=self.townhalls[0])
        self.enemy_map = np.zeros(self.game_info.map_size)
        self.enemy_map_blur = np.zeros(self.game_info.map_size)
        self.friend_map = np.zeros(self.game_info.map_size)
        self.load_heat_map()
        await self.initialize_bases()

    async def on_step(self, iteration: int):

        if 1 < self.time and self.greet_enabled:
            for tag in self.tags:
                await self.client.chat_send('Tag:' + tag, True)
            await self.client.chat_send('Rushes disabled ... for now :)', False)
            self.greet_enabled = False

        for error in self.state.action_errors:
            print(error)

        for effect in self.state.effects:
            if effect.id != EffectId.RAVAGERCORROSIVEBILECP:
                continue
            position = next(iter(effect.positions))
            if any(c.position == effect.positions for c in self.corrosive_biles):
                continue
            bile = CorrosiveBile(self.state.game_loop, position)
            self.corrosive_biles.append(bile)

        while (
            0 < len(self.corrosive_biles)
            and self.corrosive_biles[0].frame_expires <= self.state.game_loop
        ):
            self.corrosive_biles.pop(0)

        for worker in self.workers.idle:
            if any(plan.unit == worker.tag for plan in self.macro_plans):
                continue
            if worker.tag in self.bases.harvesters:
                continue
            base = min(self.bases, key = lambda b : worker.distance_to(b.position))
            base.try_add(worker.tag)

    async def on_end(self, game_result: Result):
        pass

    async def on_building_construction_started(self, unit: Unit):
        pass

    async def on_building_construction_complete(self, unit: Unit):
        if unit.type_id in race_townhalls[self.race]:
            base = next((b for b in self.bases if b.position == unit.position), None)
            if base:
                base.townhall = unit.tag
        # if unit.type_id in race_townhalls[self.race]:
        #     if self.mineral_field.exists:
        #         unit.smart(self.mineral_field.closest_to(unit))
        pass

    async def on_enemy_unit_entered_vision(self, unit: Unit):
        pass

    async def on_enemy_unit_left_vision(self, unit_tag: int):
        pass

    async def on_unit_created(self, unit: Unit):
        # if unit.type_id == race_worker[self.race]:
        #     if self.time == 0:
        #         return
        #     base = min(self.bases, key = lambda b : unit.distance_to(b.position))
        #     base.try_add(unit.tag)
        pass

    async def on_unit_destroyed(self, unit_tag: int):
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
        pass

    async def on_upgrade_complete(self, upgrade: UpgradeId):
        pass

    async def kill_random_unit(self):
        chance = self.supply_used / 200
        chance = pow(chance, 3)
        if chance < random.random():
            unit = self.all_own_units.random
            if len(self.townhalls) == 1 and unit.tag == self.townhalls[0].tag:
                return
            await self.client.debug_kill_unit(unit)

    def update_observation(self):
        self.observation.clear()
        for unit in self.all_units:
            self.observation.add_unit(unit)
        for upgrade in self.state.upgrades:
            self.observation.add_upgrade(upgrade)
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

    def save_enemy_positions(self):
        self.enemy_positions.clear()
        for enemy in self.all_enemy_units:
            self.enemy_positions[enemy.tag] = enemy.position

    def make_composition(self):
        if self.supply_used == 200:
            return
        composition_have = {
            unit: self.observation.count(unit)
            for unit in self.composition.keys()
        }
        for unit, count in self.composition.items():
            if count < 1:
                continue
            elif count <= composition_have[unit]:
                continue
            if any(self.get_missing_requirements(unit, include_pending=False, include_planned=False)):
                continue
            priority = -composition_have[unit] /  count
            plans = self.observation.planned_by_type[unit]
            if not plans:
                self.add_macro_plan(MacroPlan(unit, priority=priority))
            else:
                for plan in plans:
                    if plan.priority == BUILD_ORDER_PRIORITY:
                        continue
                    plan.priority = priority

    def update_gas(self):
        gas_target = self.get_gas_target()
        self.transfer_to_and_from_gas(gas_target)
        self.build_gasses(gas_target)

    def build_gasses(self, gas_target: int):
        gas_depleted = self.gas_buildings.filter(lambda g : not g.has_vespene).amount
        gas_have = self.observation.count(UnitTypeId.EXTRACTOR)
        gas_max = sum(1 for g in self.get_owned_geysers())
        gas_want = min(gas_max, gas_depleted + math.ceil(gas_target / 3))
        if gas_have < gas_want:
            self.add_macro_plan(MacroPlan(UnitTypeId.EXTRACTOR, priority=1))

    def get_gas_target(self):
        cost_zero = Cost(0, 0, 0)
        cost_sum = sum((self.cost[plan.item] or cost_zero for plan in self.macro_plans), cost_zero)
        cs = [self.cost[unit] * max(0, count - self.observation.count(unit, include_planned=False)) for unit, count in self.composition.items()]
        cost_sum += sum(cs, cost_zero)
        minerals = max(0, cost_sum.minerals - self.minerals)
        vespene = max(0, cost_sum.vespene - self.vespene)
        if 7 * 60 < self.time and (minerals + vespene) == 0:
            gas_ratio = 6 / 22
        else:
            gas_ratio = vespene / max(1, vespene + minerals)
        worker_type = race_worker[self.race]
        gas_target = gas_ratio * self.observation.count(worker_type, include_planned=False)
        gas_target = 3 * math.ceil(gas_target / 3)
        return gas_target

    def transfer_to_and_from_gas(self, gas_target: int):

        while self.gas_harvester_count + 1 <= gas_target:
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

        while gas_target <= self.gas_harvester_count - 1:
            gas_from = max(
                (b.vespene_geysers for b in self.bases if 0 < b.vespene_geysers.harvester_count),
                key = lambda g : g.harvester_balance,
                default = None
            )
            minerals_to = min(
                (b.mineral_patches for b in self.bases if b.mineral_patches.harvester_balance < 0),
                key = lambda m : m.harvester_balance,
                default = None
            )
            if gas_from and minerals_to and gas_from.try_transfer_to(minerals_to):
                continue
            break

    def update_bases(self):

        self.bases.update(self.observation)

    async def initialize_bases(self):

        bases = sorted((
            Base(position, (m.position for m in resources.mineral_field), (g.position for g in resources.vespene_geyser))
            for position, resources in self.expansion_locations_dict.items()
        ), key = lambda b : self.heat_map[b.position.rounded])

        self.bases = ResourceGroup(bases)
        self.bases.items[0].mineral_patches.do_worker_split(set(self.workers))

        if self.performance == PerformanceMode.DEFAULT:
            for base in self.bases:
                for minerals in base.mineral_patches:
                    minerals.speed_mining_enabled = True

    def load_heat_map(self):
        path = os.path.join('data', self.game_info.map_name + '.npy')
        try:
            with open(path, 'rb') as file:
                heat_map = np.load(file, allow_pickle=True)
        except FileNotFoundError:
            print('creating heat map ...')
            boundary = self.game_info.pathing_grid.data_numpy | self.game_info.placement_grid.data_numpy
            boundary = np.transpose(boundary) == 0
            sources = {
                loc.rounded: 1.0
                for loc in self.enemy_start_locations 
            }
            sources[self.start_location.rounded] = 0.0
            heat_map = solve_poisson_full(boundary, sources, 1.95)
            with open(path, 'wb') as file:
                np.save(file, heat_map)

        if 0.5 < heat_map[self.start_location.rounded]:
            heat_map = 1 - heat_map

        self.heat_map = heat_map
        self.heat_map_gradient = np.stack(np.gradient(heat_map), axis=-1)

    def draw_debug(self):

        if not self.debug:
            return

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

        # for p, v in np.ndenumerate(self.heat_map):
        #     if not self.in_pathing_grid(Point2(p)):
        #         continue
        #     z = self.get_terrain_z_height(Point2(p))
        #     c = int(255 * v)
        #     c = (c, 255 - c, 0)
        #     self.client.debug_text_world(f'{round(100 * v)}', Point3((*p, z)), c)

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
        exclude.update(unit.tag for units in self.observation.pending_by_type.values() for unit in units)
        took_action = False
        income_minerals, income_vespene = self.income
        self.macro_plans.sort(key = lambda t : t.priority, reverse=True)

        i = 0
        while i < len(self.macro_plans):

            plan = self.macro_plans[i]
            i += 1

            if (
                any(self.get_missing_requirements(plan.item, include_pending=False, include_planned=False))
                and plan.priority < BUILD_ORDER_PRIORITY
            ):
                continue

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

            if not plan.ability:
                plan.unit = None
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

            if took_action and plan.priority == BUILD_ORDER_PRIORITY:
                continue

            queue = False
            if unit.is_carrying_resource:
                unit.return_resource()
                queue = True

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

        trainers = sorted((
            trainer
            for trainer_type in trainer_types
            for trainer in self.observation.actual_by_type[trainer_type]
        ), key=lambda t:t.tag)
            
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
                table = TRAIN_INFO
            elif type(item) is UpgradeId:
                table = RESEARCH_INFO

            element = table.get(trainer.type_id)
            if not element:
                continue

            ability = element.get(item)

            if not ability:
                continue

            if "requires_techlab" in ability and not trainer.has_techlab:
                continue
                
            return trainer, ability

        return None, None

    def positions_in_range(self, unit: Unit) -> Iterable[Point2]:
        unit_range = math.ceil(max(unit.ground_range, unit.air_range))
        xm, ym = unit.position.rounded
        x0 = max(0, xm - unit_range)
        y0 = max(0, ym - unit_range)
        x1 = min(self.game_info.map_size[0], xm + unit_range + 1)
        y1 = min(self.game_info.map_size[1], ym + unit_range + 1)
        for x in range(x0, x1):
            for y in range(y0, y1):
                p = Point2((x, y))
                if unit.distance_to(p) <= unit_range:
                    yield p

    async def micro(self):

        friends = list(self.enumerate_army())

        enemies = self.all_enemy_units
        if self.destroy_destructables():
            enemies += self.observation.destructables
        enemies = list(enemies)

        enemy_map = np.zeros(self.game_info.map_size)
        for enemy in enemies:
            enemy_map[enemy.position.rounded] += unitValue(enemy)
            # for p in self.positions_in_range(enemy):
            #     enemy_map[p] += unitValue(enemy)

        visibility = np.transpose(self.state.visibility.data_numpy)
        self.enemy_map = np.where(visibility == 2, enemy_map, self.enemy_map)

        friend_map = np.zeros(self.game_info.map_size)
        for friend in friends:
            friend_map[friend.position.rounded] += unitValue(friend)
            # for p in self.positions_in_range(friend):
            #     friend_map[p] += unitValue(friend)

        blur_sigma = 7
        self.enemy_map_blur = ndimage.gaussian_filter(self.enemy_map, blur_sigma)
        self.friend_map = ndimage.gaussian_filter(friend_map, blur_sigma)
        # self.enemy_map_blur = self.enemy_map
        # self.friend_map = self.friend_map

        dodge_elements = list()
        dodge_elements.extend((
            (p, e.radius)
            for e in self.state.effects
            if e.id in DODGE_EFFECTS for p in e.positions
        ))
        dodge_elements.extend((
            (e.position, e.radius)
            for e in self.enemy_units(DODGE_UNITS)
        ))
        dodge_elements.extend((
            (c.position, 0.5)
            for c in self.corrosive_biles
            if c.frame_expires < self.state.game_loop + 10
        ))

        enemy_map_gradient = np.gradient(self.enemy_map_blur)
            
        for unit in friends:

            dodge_closest = min(dodge_elements, key = lambda p : unit.distance_to(p[0]) - p[1], default = None)
            if dodge_closest:
                dodge_position, dodge_radius = dodge_closest
                dodge_distance = unit.distance_to(dodge_position) - unit.radius - dodge_radius - 1
                if dodge_distance < 0:
                    unit.move(unit.position.towards(dodge_position, dodge_distance))
                    continue

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
                priority /= 10 if not target.is_enemy else 1
                if unit.is_detector:
                    priority *= 10 if target.is_cloaked else 1
                    priority *= 10 if not target.is_revealed else 1
                return priority

            target = max(enemies, key=target_priority, default=None)

            heat_gradient = Point2(self.heat_map_gradient[unit.position.rounded[0], unit.position.rounded[1],:])
            if 0 < heat_gradient.length:
                heat_gradient = heat_gradient.normalized

            enemy_gradient = Point2((
                enemy_map_gradient[0][unit.position.rounded],
                enemy_map_gradient[1][unit.position.rounded],
            ))
            if 0 < enemy_gradient.length:
                enemy_gradient = enemy_gradient.normalized

            gradient = heat_gradient + enemy_gradient
            if 0 < gradient.length:
                gradient = gradient.normalized
            else:
                gradient = (unit.position - target.position).normalized

            if target and 0 < target_priority(target):

                if target.is_enemy:
                    attack_target = target.position
                else:
                    attack_target = target

                # friends_rating = sum(unitValue(f) / max(1, target.distance_to(f)) for f in friends)
                # enemies_rating = sum(unitValue(e) / max(1, unit.distance_to(e)) for e in enemies)

                friends_rating = self.friend_map[unit.position.rounded]
                enemies_rating = self.enemy_map_blur[unit.position.rounded]
                advantage_army = friends_rating / max(1, enemies_rating)

                advantage_defender = 1.5 - self.heat_map[unit.position.rounded]

                advantage_creep = 1
                creep_bonus = SPEED_INCREASE_ON_CREEP_DICT.get(unit.type_id)
                if creep_bonus and self.state.creep.is_empty(unit.position.rounded):
                    advantage_creep = 1 / creep_bonus

                advantage = 1
                advantage *= advantage_army
                # advantage *= advantage_defender
                advantage *= advantage_creep
                advantage_threshold = 1

                retreat_target = unit.position - 12 * gradient

                if advantage < advantage_threshold / 3:

                    # FLEE
                    if not unit.is_moving:
                        unit.move(retreat_target)

                elif advantage < advantage_threshold:

                    # RETREAT
                    if unit.weapon_cooldown and unit.target_in_range(target, unit.distance_to_weapon_ready):
                        unit.move(retreat_target)
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
                    # if not b.remaining:
                    #     continue
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