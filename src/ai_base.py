
from abc import ABC
from asyncio import gather
import cProfile, pstats
from collections import defaultdict
from enum import Enum
from dataclasses import dataclass
from functools import cache, cmp_to_key
from importlib.resources import Resource
import math
from pickle import BUILD
import re
import random
from re import S
from typing import Any, DefaultDict, Iterable, Optional, Tuple, Type, Union, Coroutine, Set, List, Callable, Dict
from matplotlib.colors import Normalize
import numpy as np
import os
import json
import MapAnalyzer
import skimage.draw
import matplotlib.pyplot as plt

from MapAnalyzer import MapData
from sc2.game_data import GameData

from sc2.data import Alliance
from sc2.game_state import ActionRawUnitCommand
from sc2.ids.effect_id import EffectId
from sc2 import game_info, game_state
from sc2.position import Point2, Point3
from sc2.bot_ai import BotAI
from sc2.constants import IS_DETECTOR, SPEED_INCREASE_ON_CREEP_DICT, IS_STRUCTURE, TARGET_AIR, TARGET_GROUND
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.effect_id import EffectId
from sc2.ids.ability_id import AbilityId
from sc2.ids.upgrade_id import UpgradeId
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.unit_research_abilities import RESEARCH_INFO
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.dicts.unit_tech_alias import UNIT_TECH_ALIAS
from sc2.data import Result, race_townhalls, race_worker, ActionResult
from sc2.unit import Unit, UnitOrder
from sc2.unit_command import UnitCommand
from sc2.units import Units
from src.techtree import TechTree, TechTreeWeaponType

from .modules.chat import Chat
from .modules.module import AIModule
from .modules.creep import Creep
from .modules.combat import CombatBehavior, CombatManager
from .modules.drop_manager import DropManager
from .modules.macro import MacroId, MacroManager, MacroPlan
from .modules.bile import BileManager
from .resources.mineral_patch import MineralPatch
from .resources.vespene_geyser import VespeneGeyser
from .modules.scout_manager import ScoutManager
from .modules.unit_manager import IGNORED_UNIT_TYPES, UnitManager
from .simulation.simulation import Simulation
from .value_map import ValueMap
from .resources.base import Base
from .resources.resource_group import BalancingMode, ResourceGroup
from .modules.dodge import *
from .constants import *
from .cost import Cost
from .utils import *
from .modules.dodge import *
from .enums import PerformanceMode

VERSION_PATH = 'version.txt'

@dataclass
class MapStaticData:

    version: np.ndarray
    distance: np.ndarray

    def flip(self):
        self.distance = 1 - self.distance

class AIBase(ABC, BotAI):

    def __init__(self):

        self.raw_affects_selection = True

        self.version: str = ''
        self.game_step: int = 2
        self.performance: PerformanceMode = PerformanceMode.DEFAULT
        self.debug: bool = False
        self.destroy_destructables: bool = False
        self.unit_command_uses_self_do = True

        self.composition: Dict[UnitTypeId, int] = dict()
        self.cost: Dict[MacroId, Cost] = dict()
        self.weapons: Dict[UnitTypeId, List] = dict()
        self.dps: Dict[UnitTypeId, float] = dict()
        self.resource_by_position: Dict[Point2, Unit] = dict()
        self.townhall_by_position: Dict[Point2, Unit] = dict()
        self.gas_building_by_position: Dict[Point2, Unit] = dict()
        self.unit_by_tag: Dict[int, Unit] = dict()
        self.enemies: Dict[int, Unit] = dict()
        self.enemies_by_type: DefaultDict[UnitTypeId, Set[Unit]] = defaultdict(lambda:set())
        self.actual_by_type: DefaultDict[MacroId, Set[Unit]] = defaultdict(lambda:set())
        self.pending_by_type: DefaultDict[MacroId, Set[Unit]] = defaultdict(lambda:set())
        self.damage_taken: Dict[int] = dict()
        self.army: List[Unit] = list()

        self.opponent_name: Optional[str] = None
        self.map_data: MapStaticData = None
        self.map_analyzer: MapData = None
        
        self.extractor_trick_enabled: bool = False
        self.max_gas: bool = False
        self.iteration: int = 0
        self.techtree: TechTree = TechTree('data/techtree.json')

        super().__init__()

    @property
    def is_speedmining_enabled(self) -> bool:
        if self.performance is PerformanceMode.DEFAULT:
            return True
        elif self.performance is PerformanceMode.HIGH_PERFORMANCE:
            return False
        raise Exception

    async def on_before_start(self):

        if self.debug:
            plt.ion()
            self.plot, self.plot_axes = plt.subplots(1, 2)
            self.plot_images = None

        with open(VERSION_PATH, 'r') as file:
            self.version = file.readline().replace('\n', '')

        for unit in UnitTypeId:
            data = self.game_data.units.get(unit.value)
            if not data:
                continue
            weapons = list(data._proto.weapons)
            self.weapons[unit] = weapons
            dps = 0
            for weapon in weapons:
                damage = weapon.damage
                speed = weapon.speed
                dps = max(dps, damage / speed)
            self.dps[unit] = dps

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

        self.map_analyzer = MapData(self)
        self.map_data = await self.load_map_data()
        
        await self.initialize_bases()

        self.scout_manager = ScoutManager(self)
        self.drop_manager = DropManager(self)
        self.unit_manager = UnitManager(self)
        self.macro = MacroManager(self)
        self.chat = Chat(self)
        self.creep = Creep(self)
        self.biles = BileManager(self)
        self.combat = CombatManager(self)
        self.dodge = DodgeManager(self)

        self.modules: List[AIModule] = [
            self.dodge,
            self.combat,
            self.scout_manager,
            self.drop_manager,
            self.macro,
            self.chat,
            self.creep,
            self.biles,
            self.unit_manager,
        ]

        # await self.client.debug_create_unit([
        #     [UnitTypeId.ZERGLINGBURROWED, 1, self.bases[1].position, 2],
        # ])

    def handle_errors(self):
        for error in self.state.action_errors:
            print(self.time, error)
            if error.result == ActionResult.CantBuildLocationInvalid.value:
                if unit := self.unit_by_tag.get(error.unit_tag):
                    self.scout_manager.blocked_positions[unit.position] = self.time

    def units_detecting(self, unit: Unit) -> Iterable[Unit]:
        for detector_type in IS_DETECTOR:
            for detector in self.actual_by_type[detector_type]:
                distance = detector.position.distance_to(unit.position)
                if distance <= detector.radius + detector.detect_range + unit.radius:
                    yield detector
        pass

    def can_attack(self, unit: Unit, target: Unit) -> bool:
        if target.is_cloaked and not target.is_revealed:
            return False
        elif target.is_burrowed and not any(self.units_detecting(target)):
            return False
        elif target.is_flying:
            return unit.can_attack_air
        else:
            return unit.can_attack_ground

    def handle_actions(self):
        for action in self.state.actions_unit_commands:
            if item := ITEM_BY_ABILITY.get(action.exact_id):
                self.macro.remove_plan_by_item(item)

    async def on_step(self, iteration: int):
        
        self.iteration = iteration
        
        profiler = None
        if iteration % 1000 == 0:
            profiler = cProfile.Profile()
            profiler.enable()

        self.update_tables()
        self.handle_errors()
        self.handle_actions()
        self.update_bases()
        self.update_gas()

        for module in self.modules:
            await module.on_step()

        if profiler:
            print(f'Iteration {iteration}')
            profiler.disable()
            stats = pstats.Stats(profiler)
            stats.strip_dirs().sort_stats(pstats.SortKey.TIME).print_stats(32)
            if self.debug:
                stats.dump_stats(filename='profiling.prof')

        if self.debug:
            await self.draw_debug()

    async def on_end(self, game_result: Result):
        pass

    async def on_building_construction_started(self, unit: Unit):
        print(self.time, 'construction_started', unit)
        pass

    async def on_building_construction_complete(self, unit: Unit):
        print(self.time, 'construction_complete', unit)
        pass

    async def on_enemy_unit_entered_vision(self, unit: Unit):
        pass

    async def on_enemy_unit_left_vision(self, unit_tag: int):
        pass

    async def on_unit_created(self, unit: Unit):
        print(self.time, 'created', unit)
        if 0 < self.state.game_loop and unit.type_id == race_worker[self.race]:
            self.bases.try_add(unit.tag)
        pass

    async def on_unit_destroyed(self, unit_tag: int):
        print(self.time, 'destroyed', unit_tag)
        self.enemies.pop(unit_tag, None)
        self.bases.try_remove(unit_tag)
        pass

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float):
        if unit.is_structure and not unit.is_ready:
            should_cancel = False
            if unit.shield_health_percentage < 0.1:
                should_cancel = True
            if should_cancel:
                unit(AbilityId.CANCEL)
        self.damage_taken[unit.tag] = self.time
        pass
        
    async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId):
        print(self.time, 'type_changed', previous_type, unit)
        pass

    async def on_upgrade_complete(self, upgrade: UpgradeId):
        pass

    def count(self,
        item: MacroId,
        include_pending: bool = True,
        include_planned: bool = True,
        include_actual: bool = True
    ) -> int:

        factor = 2 if item == UnitTypeId.ZERGLING else 1
        
        sum = 0
        if include_actual:
            if item in WORKERS:
                sum += self.state.score.food_used_economy
            else:
                sum += len(self.actual_by_type[item])
        if include_pending:
            sum += factor * len(self.pending_by_type[item])
        if include_planned:
            sum += factor * len(self.macro.planned_by_type[item])

        return sum

    def update_tables(self):

        self.army = [
            unit
            for unit in self.units
            if unit.type_id not in CIVILIANS or unit.tag in self.unit_manager.drafted_civilians
        ]

        enemies_remembered = self.enemies.copy()
        self.enemies = {
            enemy.tag: enemy
            for enemy in self.all_enemy_units
            if not enemy.is_snapshot
        }
        for tag, enemy in enemies_remembered.items():
            if tag in self.enemies:
                # can see
                continue
            visible = True
            for offset in {(0, 0), (0, 1), (0, -1), (1, 0), (-1, 0)}:
                if not self.is_visible(enemy.position.offset(offset)):
                    visible = False
            if visible:
                continue
            # cannot see, maybe still there
            self.enemies[tag] = enemy

        self.enemies_by_type.clear()
        for enemy in self.enemies.values():
            self.enemies_by_type[enemy.type_id].add(enemy)
        
        self.actual_by_type.clear()
        self.pending_by_type.clear()
        
        for unit in self.all_own_units:
            if unit.is_ready:
                self.actual_by_type[unit.type_id].add(unit)
            else:
                self.pending_by_type[unit.type_id].add(unit)
            for order in unit.orders:
                ability = order.ability.exact_id
                if item := ITEM_BY_ABILITY.get(ability):
                    self.pending_by_type[item].add(unit)
            
        self.resource_by_position = {
            resource.position: resource
            for resource in self.resources
        }
        self.gas_building_by_position = {
            gas.position: gas
            for gas in self.gas_buildings
        }
        self.townhall_by_position = {
            townhall.position: townhall
            for townhall in self.townhalls
            if townhall.is_ready
        }
        self.unit_by_tag = {
            unit.tag: unit
            for unit in self.all_units
        }
        self.actual_by_type.update((upgrade, {upgrade}) for upgrade in self.state.upgrades)

    def update_gas(self):
        gas_target = self.get_gas_target()
        self.transfer_to_and_from_gas(gas_target)
        self.build_gasses(gas_target)

    def build_gasses(self, gas_target: float):
        gas_depleted = self.gas_buildings.filter(lambda g : not g.has_vespene).amount
        gas_pending = self.count(UnitTypeId.EXTRACTOR, include_actual=False)
        gas_have = self.count(UnitTypeId.EXTRACTOR, include_pending=False, include_planned=False)
        gas_max = sum(1 for g in self.get_owned_geysers())
        gas_want = min(gas_max, gas_depleted + math.ceil(gas_target / 3))
        if gas_have + gas_pending < gas_want:
            self.macro.add_plan(MacroPlan(UnitTypeId.EXTRACTOR))
        else:
            for _, plan in zip(range(gas_have + gas_pending - gas_want), list(self.macro.planned_by_type[UnitTypeId.EXTRACTOR])):
                if plan.priority < BUILD_ORDER_PRIORITY:
                    self.macro.remove_plan(plan)

    def get_gas_target(self) -> float:

        if self.max_gas:
            return sum(g.ideal_harvesters for g in self.gas_buildings.ready)

        cost_zero = Cost(0, 0, 0)
        cost_sum = sum((self.cost[plan.item] for plan in self.macro.plans), cost_zero)
        cost_sum += sum(
            (self.cost[unit] * max(0, count - self.count(unit))
            for unit, count in self.composition.items()),
            cost_zero)
        minerals = max(0, cost_sum.minerals - self.minerals)
        vespene = max(0, cost_sum.vespene - self.vespene)
        if minerals + vespene == 0:
            minerals = sum(b.mineral_patches.remaining for b in self.bases if b.townhall)
            vespene = sum(b.vespene_geysers.remaining for b in self.bases if b.townhall)

        gas_ratio = vespene / max(1, vespene + minerals)
        worker_type = race_worker[self.race]
        gas_target = gas_ratio * self.count(worker_type, include_pending=False)

        return gas_target

    def transfer_to_and_from_gas(self, gas_target: float):

        effective_gas_target = min(self.vespene_geysers.harvester_target, gas_target)
        effective_gas_balance = self.vespene_geysers.harvester_count - effective_gas_target

        # if self.gas_harvester_count + 1 <= gas_target and self.vespene_geysers.harvester_balance < 0:
        if 0 < self.mineral_patches.harvester_count and (effective_gas_balance < 0 or 0 < self.mineral_patches.harvester_balance):

            if not self.mineral_patches.try_transfer_to(self.vespene_geysers):
                print('transfer to gas failure')

        # elif gas_target <= self.gas_harvester_count - 1 or 0 < self.vespene_geysers.harvester_balance:
        elif 0 < self.vespene_geysers.harvester_count and (1 <= effective_gas_balance and self.mineral_patches.harvester_balance < 0):

            if not self.vespene_geysers.try_transfer_to(self.mineral_patches):
                print('transfer from gas failure')
        
    def update_bases(self):

        for base in self.bases:
            base.defensive_units.clear()
            base.defensive_units_planned.clear()

        for unit_type in STATIC_DEFENSE[self.race]:
            for unit in chain(self.actual_by_type[unit_type], self.pending_by_type[unit_type]):
                base = min(self.bases, key=lambda b:b.position.distance_to(unit.position))
                base.defensive_units.append(unit)
            for plan in self.macro.planned_by_type[unit_type]:
                if not isinstance(plan.target, Point2):
                    continue
                base = min(self.bases, key=lambda b:b.position.distance_to(plan.target))
                base.defensive_units_planned.append(plan)

        self.bases.update()
        self.mineral_patches.update()
        self.vespene_geysers.update()

    async def initialize_bases(self):

        exclude_bases = {
            self.start_location,
            *self.enemy_start_locations
        }
        positions_fixed = dict()
        for b in self.expansion_locations_list:
            if b in exclude_bases:
                continue
            if await self.can_place_single(UnitTypeId.HATCHERY, b):
                continue
            positions_fixed[b] = await self.find_placement(UnitTypeId.HATCHERY, b, placement_step=1)


        bases = sorted((
            Base(self, positions_fixed.get(position, position), (m.position for m in resources.mineral_field), (g.position for g in resources.vespene_geyser))
            for position, resources in self.expansion_locations_dict.items()
        ), key = lambda b : self.map_data.distance[b.position.rounded] - .5 * b.position.distance_to(self.enemy_start_locations[0]) / self.game_info.map_size.length)

        self.bases = ResourceGroup(self, bases)
        self.bases.balancing_mode = BalancingMode.NONE
        self.bases[0].split_initial_workers(set(self.workers))

        self.vespene_geysers = ResourceGroup(self, [b.vespene_geysers for b in self.bases])
        self.mineral_patches = ResourceGroup(self, [b.mineral_patches for b in self.bases])

    async def load_map_data(self) -> Coroutine[Any, Any, MapStaticData]:

        path = os.path.join('data', f'{self.game_info.map_name}.npz')
        try:
            map_data_files = np.load(path)
            map_data = MapStaticData(**map_data_files)
            map_data_version = str(map_data.version)
            if map_data_version != self.version:
                raise VersionConflictException()
            if 0.5 < map_data.distance[self.start_location.rounded]:
                map_data.flip()
        except (FileNotFoundError, VersionConflictException, TypeError):
            map_data = await self.create_map_data()
            np.savez_compressed(path, **map_data.__dict__)
        return map_data

    async def create_map_data(self) -> Coroutine[Any, Any, MapStaticData]:
        print('creating map data ...')
        distance_map = await self.create_distance_map()
        return MapStaticData(self.version, distance_map)

    async def create_distance_map(self) -> Coroutine[Any, Any, np.ndarray]:

        boundary = np.transpose(self.game_info.pathing_grid.data_numpy == 0)
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                p = self.start_location + Point2((dx, dy))
                boundary[p.rounded] = False

        distance_ground_self = flood_fill(boundary, [self.start_location.rounded])
        distance_ground_enemy = flood_fill(boundary, [p.rounded for p in self.enemy_start_locations])
        distance_ground = distance_ground_self / (distance_ground_self + distance_ground_enemy)
        distance_air = np.zeros_like(distance_ground)
        for p, _ in np.ndenumerate(distance_ground):
            position = Point2(p)
            distance_self = position.distance_to(self.start_location)
            distance_enemy = min(position.distance_to(p) for p in self.enemy_start_locations)
            distance_air[p] = distance_self / (distance_self + distance_enemy)
        distance_map = np.where(np.isnan(distance_ground), distance_air, distance_ground)
        
        return distance_map

    async def draw_debug(self):

        font_color = (255, 255, 255)
        font_size = 12

        for i, target in enumerate(self.macro.plans):

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
                unit = self.unit_by_tag.get(target.unit)
                if unit:
                    positions.append(unit)

            text = f"{str(i+1)} {str(target.item.name)}"

            for position in positions:
                self.client.debug_text_world(text, position, color=font_color, size=font_size)

        # for unit in chain(self.unit_manager.simulation.units_lost.keys(), self.unit_manager.simulation.enemies_killed.keys()):
        #     u = self.unit_by_tag.get(unit.tag) or self.enemies.get(unit.tag)
        #     if not u:
        #         continue
        #     pos = u.position
        #     z = self.get_terrain_z_height(pos)
        #     position = Point3((*pos, z))
        #     text = f"{str(unit.tag)}"
        #     self.client.debug_text_world(text, position, color=font_color, size=font_size)

        self.client.debug_text_screen(f'Threat Level: {round(100 * self.combat.threat_level)}%', (0.01, 0.01))
        self.client.debug_text_screen(f'Enemy Bases: {len(self.scout_manager.enemy_bases)}', (0.01, 0.02))
        self.client.debug_text_screen(f'Gas Target: {round(self.get_gas_target(), 3)}', (0.01, 0.03))
        # self.client.debug_text_screen(f'Simulation Resullt: {round(self.unit_manager.simulation_result, 3)}', (0.01, 0.04))
        self.client.debug_text_screen(f'Creep Coverage: {round(100 * self.creep.coverage)}%', (0.01, 0.06))
        for i, plan in enumerate(self.macro.plans):
            self.client.debug_text_screen(f'{1+i} {plan.item.name}', (0.01, 0.1 + 0.01 * i))

        # self.map_analyzer.draw_influence_in_game(self.unit_manager.simulation_map)

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
        requirements = [r for r in requirements if r not in { UnitTypeId.LARVA, UnitTypeId.CORRUPTOR, UnitTypeId.ROACH, UnitTypeId.ZERGLING }]
        
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
            if any(self.count(e, **kwargs) for e in equivalents):
                continue
            missing.add(requirement)
            requirements.extend(self.get_missing_requirements(requirement, **kwargs))

        return missing

    def get_owned_geysers(self):
        for base in self.bases:
            if base.position not in self.townhall_by_position.keys():
                continue
            for gas in base.vespene_geysers:
                geyser = self.resource_by_position.get(gas.position)
                if not geyser:
                    continue
                yield geyser

    def order_to_command(self, unit: Unit, order: UnitOrder) -> UnitCommand:
        ability = order.ability.exact_id
        target = None
        if isinstance(order.target, Point2):
            target = order.target
        elif isinstance(order.target, int):
            target = self.unit_by_tag.get(order.target)
        return UnitCommand(ability, unit, target)

    def order_matches_command(self, order: UnitOrder, command: UnitCommand) -> bool:
        if order.ability.exact_id != command.ability:
            return False
        if isinstance(order.target, Point2):
            if not isinstance(command.target, Point2):
                return False
            elif 1e-3 < order.target.distance_to(command.target):
                return False
        elif isinstance(order.target, int):
            if not isinstance(command.target, Unit):
                return False
            elif order.target != command.target.tag:
                return False
        return True

    def get_unit_range(self, unit: Unit, ground: bool = True, air: bool = True) -> float:
        unit_range = 0
        if ground:
            unit_range = max(unit_range, unit.ground_range)
        if air:
            unit_range = max(unit_range, unit.air_range)
        unit_range += unit_boni(unit, RANGE_UPGRADES)
        return unit_range

    def enumerate_enemies(self) -> Iterable[Unit]:
        for unit in self.enemies.values():
            if unit.type_id in IGNORED_UNIT_TYPES:
                continue
            yield unit
        if self.destroy_destructables:
            for unit in self.destructables:
                if unit.armor == 0:
                    continue
                yield unit

    def is_structure(self, unit: UnitTypeId) -> bool:
        if data := self.game_data.units.get(unit.value):
            return IS_STRUCTURE in data.attributes
        return False

    def get_unit_value(self, unit: Unit) -> float:
        health = unit.health + unit.shield
        dps =  max(unit.ground_dps, unit.air_dps)
        return math.sqrt(health * dps)

    def get_unit_cost(self, unit_type: UnitTypeId) -> int:
        cost = self.calculate_unit_value(unit_type)
        return cost.minerals + cost.vespene

    def can_afford_with_reserve(self, cost: Cost, reserve: Cost) -> bool:
        if max(0, self.minerals - reserve.minerals) < cost.minerals:
            return False
        elif max(0, self.vespene - reserve.vespene) < cost.vespene:
            return False
        elif max(0, self.supply_left - reserve.food) < cost.food:
            return False
        else:
            return True

    def get_max_harvester(self) -> int:
        workers = 0
        workers += sum((b.harvester_target for b in self.bases))
        workers += 16 * self.count(UnitTypeId.HATCHERY, include_actual=False, include_planned=False)
        workers += 3 * self.count(GAS_BY_RACE[self.race], include_actual=False, include_planned=False)
        return workers

    def blocked_bases(self, position: Point2, margin: float = 0.0) -> Iterable[Base]:
        px, py = position
        radius = 3
        for base in self.bases:
            bx, by = base.position
            if abs(px - bx) < margin + radius and abs(py - by) < margin + radius:
                yield base