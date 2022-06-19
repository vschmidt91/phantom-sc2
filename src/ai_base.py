
from abc import ABC
import cProfile, pstats
from functools import cmp_to_key
import mailcap
import itertools
from collections import defaultdict
from dataclasses import dataclass
import logging
import uuid
import asyncio
import math
from random import random
from typing import Any, DefaultDict, Iterable, Optional, Tuple, Type, Union, Coroutine, Set, List, Callable, Dict
from loguru import logger
import numpy as np
import os
import json

from pkg_resources import require
import MapAnalyzer
import skimage.draw

from MapAnalyzer import MapData
from sc2 import unit
from sc2.game_data import GameData
from sc2.game_state import ActionRawUnitCommand

from sc2.position import Point2, Point3
from sc2.bot_ai import BotAI
from sc2.constants import IS_DETECTOR
from sc2.ids.unit_typeid import UnitTypeId
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
from src.resources.resource_manager import ResourceManager
from src.resources.resource_unit import ResourceUnit

from src.strategies.hatch_first import HatchFirst
from src.strategies.pool_first import PoolFirst
from src.techtree import TechTree, TechTreeWeaponType
from src.units.structure import Structure
from src.units.unit import EnemyUnit

from .modules.chat import Chat
from .behaviors.inject import InjectManager
from .modules.module import AIModule
from .modules.creep import CreepModule
from .modules.combat import CombatBehavior, CombatModule
from .modules.drop import DropModule
from .behaviors.gather import GatherBehavior
from .behaviors.survive import SurviveBehavior
from .modules.macro import MacroBehavior, MacroId, MacroModule, MacroPlan, compare_plans
from .modules.bile import BileModule
from .resources.mineral_patch import MineralPatch
from .resources.vespene_geyser import VespeneGeyser
from .modules.scout import ScoutModule
from .modules.unit_manager import IGNORED_UNIT_TYPES, UnitManager
from .strategies.strategy import Strategy
from .simulation.simulation import Simulation
from .value_map import ValueMap
from .resources.base import Base
from .resources.resource_group import ResourceGroup
from .modules.dodge import *
from .constants import *
from .units.worker import Worker, WorkerManager
from .cost import Cost
from .utils import *
from .modules.dodge import *

VERSION_PATH = 'version.txt'

@dataclass
class MapStaticData:

    version: np.ndarray
    distance: np.ndarray

    def flip(self):
        self.distance = 1 - self.distance

class AIBase(BotAI):

    def __init__(self, strategy_cls: Optional[Type[Strategy]] = None):

        self.raw_affects_selection = True
        self.game_step: int = 2

        self.strategy_cls: Type[Strategy] = strategy_cls or PoolFirst
        self.version: str = ''
        self.debug: bool = False
        self.destroy_destructables: bool = False
        self.unit_command_uses_self_do = True

        self.cost: Dict[MacroId, Cost] = dict()
        self.weapons: Dict[UnitTypeId, List] = dict()
        self.dps: Dict[UnitTypeId, float] = dict()

        self.enemies: Dict[int, Unit] = dict()

        self.map_data: MapStaticData = None
        self.map_analyzer: MapData = None
        
        self.extractor_trick_enabled: bool = False
        self.iteration: int = 0
        self.techtree: TechTree = TechTree('data/techtree.json')
        self.profiler: Optional[cProfile.Profile] = None

        super().__init__()

    async def on_before_start(self):

        if self.debug:
            logging.basicConfig(level=logging.DEBUG)
            self.profiler = cProfile.Profile()
            # plt.ion()
            # self.plot, self.plot_axes = plt.subplots(1, 2)
            # self.plot_images = None
        else:
            logging.basicConfig(level=logging.ERROR)

        logging.debug(f'before_start')

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
                larva = LARVA_COST.get(unit, 0.0)
                self.cost[unit] = Cost(cost.minerals, cost.vespene, food, larva)
            except:
                pass
        for upgrade in UpgradeId:
            try:
                cost = self.calculate_cost(upgrade)
                self.cost[upgrade] = Cost(cost.minerals, cost.vespene, 0, 0)
            except:
                pass

    async def on_start(self):

        logging.debug(f'start')

        for th in self.townhalls:
            self.do(th(AbilityId.RALLY_WORKERS, target=th))

        self.map_analyzer = MapData(self)
        self.map_data = await self.load_map_data()
        bases = await self.initialize_bases()
        self.resource_manager = ResourceManager(self, bases)
        self.scout = ScoutModule(self)
        self.drop = DropModule(self)
        self.unit_manager = UnitManager(self)
        self.macro = MacroModule(self)
        self.chat = Chat(self)
        self.creep = CreepModule(self)
        self.biles = BileModule(self)
        self.combat = CombatModule(self)
        self.dodge = DodgeModule(self)
        self.inject = InjectManager(self)
        self.strategy: Strategy = self.strategy_cls(self)
        self.worker_manager: WorkerManager = WorkerManager(self)

        self.modules: List[AIModule] = [
            self.unit_manager,
            self.resource_manager,
            self.scout,
            self.drop,
            self.macro,
            self.dodge,
            self.combat,
            self.chat,
            self.creep,
            self.biles,
            self.inject,
            self.strategy,
            self.worker_manager
        ]

        for structure in self.all_own_units:
            self.unit_manager.add_unit(structure)

        # await self.client.debug_create_unit([
        #     [UnitTypeId.ZERGLINGBURROWED, 1, self.bases[1].position, 2],
        # ])

    def handle_errors(self):
        for error in self.state.action_errors:
            if error.result == ActionResult.CantBuildLocationInvalid.value:
                if behavior := self.unit_manager.units.get(error.unit_tag):
                    self.scout.blocked_positions[behavior.unit.position] = self.time

    def units_detecting(self, unit: Unit) -> Iterable[CommandableUnit]:
        for detector_type in IS_DETECTOR:
            for detector in self.unit_manager.actual_by_type[detector_type]:
                distance = detector.unit.position.distance_to(unit.position)
                if distance <= detector.unit.radius + detector.unit.detect_range + unit.radius:
                    yield detector

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
            for tag in action.unit_tags:
                self.handle_action(action, tag)
                    
    def handle_action(self, action: ActionRawUnitCommand, tag: int) -> None:

        if action.exact_id == AbilityId.BUILD_CREEPTUMOR_TUMOR:
            if not self.unit_manager.try_remove_unit(tag):
                logging.error(f'creep tumor not found')

        behavior = self.unit_manager.units.get(tag)
        if not behavior:
            return
        elif not behavior.unit:
            return
        elif behavior.unit.type_id == UnitTypeId.DRONE:
            return
        elif behavior.unit.type_id in { UnitTypeId.LARVA, UnitTypeId.EGG }:
            candidates = chain(self.unit_manager.actual_by_type[UnitTypeId.LARVA], self.unit_manager.actual_by_type[UnitTypeId.EGG])
        else:
            candidates = (behavior,)
        behavior = next((
                b
                for b in candidates
                if (
                    isinstance(b, MacroBehavior)
                    and b.plan
                    and b.macro_ability == action.exact_id
                )
            ),
            None)
        if behavior:
            behavior.plan = None
        # else:
        #     logging.error(f'trainer not found: {action}')

    async def kill_random_units(self, chance: float = 3e-4) -> None:
        tags = [
            unit.tag
            for unit in self.all_own_units
            if random() < chance
        ]
        if tags:
            await self.client.debug_kill_unit(tags)


    async def on_step(self, iteration: int):

        # logging.debug(f'step: {iteration}')

        if iteration == 0 and self.debug:
            return
        
        self.iteration = iteration

        if 1 < self.time:
            await self.chat.add_tag(self.version, False)
            await self.chat.add_tag(self.strategy.name, False)

        if self.profiler:
            self.profiler.enable()

        if self.extractor_trick_enabled and self.supply_left <= 0:
            for gas in self.gas_buildings.not_ready:
                self.do(gas(AbilityId.CANCEL))
                self.extractor_trick_enabled = False
                break

        self.handle_errors()
        self.handle_actions()

        # for module in self.modules:
        #     await module.on_step()
        await asyncio.gather(*[m.on_step() for m in self.modules])

        if self.profiler:
            self.profiler.disable()
            stats = pstats.Stats(self.profiler)
            if iteration % 100 == 0:
                logging.info('dump profiling')
                stats = stats.strip_dirs().sort_stats(pstats.SortKey.CUMULATIVE)
                stats.dump_stats(filename='profiling.prof')

        if self.debug:
            await self.draw_debug()

        if self.debug:
            # if 90 < self.time:
            #     await self.kill_random_units()
            worker_count = sum(1 for b in self.unit_manager.units.values() if isinstance(b, Worker))
            if worker_count != self.supply_workers:
                logging.error('worker supply mismatch')

    async def on_end(self, game_result: Result):
        logging.debug(f'end: {game_result}')

    async def on_building_construction_started(self, unit: Unit):
        logging.debug(f'building_construction_started: {unit}')

        behavior = self.unit_manager.add_unit(unit)
        # self.unit_manager.pending_by_type[unit.type_id].append(behavior)

        if self.race == Race.Zerg:
            if unit.type_id in { UnitTypeId.CREEPTUMOR, UnitTypeId.CREEPTUMORQUEEN, UnitTypeId.CREEPTUMORBURROWED }:
                # print('tumor')
                pass
            else:
                geyser = self.resource_manager.resource_by_position.get(unit.position)
                geyser_tag = geyser.unit.tag if isinstance(geyser, VespeneGeyser) else None
                for trainer_type in UNIT_TRAINED_FROM.get(unit.type_id, []):
                    for trainer in self.unit_manager.actual_by_type[trainer_type]:
                        if not trainer.unit:
                            pass
                        elif trainer.unit.position.distance_to(unit.position) < 0.1:
                            if behavior := self.unit_manager.units.get(trainer.unit.tag):
                                if isinstance(behavior, MacroBehavior):
                                    behavior.plan = None
                            assert self.unit_manager.try_remove_unit(trainer.unit.tag)
                            break
                        elif (
                            not trainer.unit.is_idle
                            and trainer.unit.order_target in {unit.position, geyser_tag}
                            # and ITEM_BY_ABILITY.get(trainer.orders[0].ability.exact_id) == unit.type_id
                        ):
                            assert self.unit_manager.try_remove_unit(trainer.unit.tag)
                            break
                    else:
                        logging.error('trainer not found')
        pass

    async def on_building_construction_complete(self, unit: Unit):
        logging.debug(f'building_construction_complete: {unit}')

    async def on_enemy_unit_entered_vision(self, unit: Unit):
        logging.debug(f'enemy_unit_entered_vision: {unit}')
        if unit.is_snapshot:
            return
        if unit.tag not in self.unit_manager.enemies:
            self.unit_manager.add_unit(unit)

    async def on_enemy_unit_left_vision(self, unit_tag: int):
        logging.debug(f'enemy_unit_left_vision: {unit_tag}')
        if enemy := self.unit_manager.enemies.get(unit_tag):
            enemy.snapshot = enemy.unit
        else:
            logging.error('enemy not found')

    async def on_unit_destroyed(self, unit_tag: int):
        logging.debug(f'unit_destroyed: {unit_tag}')
        if unit_tag in self._enemy_units_previous_map or unit_tag in self._enemy_structures_previous_map:
            self.unit_manager.enemies.pop(unit_tag, None)
            # del self.unit_manager.enemies[unit_tag]
        elif not self.unit_manager.try_remove_unit(unit_tag):
            logging.error('destroyed unit not found')

    async def on_unit_created(self, unit: Unit):
        logging.debug(f'unit_created: {unit}')
        behavior = self.unit_manager.add_unit(unit)
        
    async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId):
        logging.debug(f'unit_type_changed: {previous_type} -> {unit}')
                
    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float):
        logging.debug(f'unit_took_damage: {amount_damage_taken} @ {unit}')
        if behavior := self.unit_manager.units.get(unit.tag):
            if isinstance(behavior, SurviveBehavior):
                behavior.last_damage_taken = self.time
            # elif isinstance(behavior, Structure) and not behavior.is_ready:
            #     if unit.shield_health_percentage < 0.1:
            #         behavior.cancel = True
            #     elif unit.type_id in CREEP_TUMORS:
            #         behavior.cancel = True

    async def on_upgrade_complete(self, upgrade: UpgradeId):
        logging.info(f'upgrade_complete: {upgrade}')

    def count(self,
        item: MacroId,
        include_pending: bool = True,
        include_planned: bool = True,
        include_actual: bool = True
    ) -> int:

        factor = 2 if item == UnitTypeId.ZERGLING else 1
        
        count = 0
        if include_actual:
            if item in WORKERS:
                count += self.state.score.food_used_economy
            else:
                count += len(self.unit_manager.actual_by_type[item])
        if include_pending:
            count += factor * len(self.unit_manager.pending_by_type[item])
        if include_planned:
            count += factor * sum(1 for _ in self.macro.planned_by_type(item))

        return count

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
            Base(self,positions_fixed.get(position, position), (MineralPatch(self, m) for m in resources.mineral_field), (VespeneGeyser(self, g) for g in resources.vespene_geyser))
            for position, resources in self.expansion_locations_dict.items()
        ), key = lambda b : self.map_data.distance[b.position.rounded] - .5 * b.position.distance_to(self.enemy_start_locations[0]) / self.game_info.map_size.length)

        return bases

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

        plans = []
        plans.extend(b.plan
            for b in self.unit_manager.units.values()
            if isinstance(b, MacroBehavior) and b.plan
        )
        plans.extend(self.macro.unassigned_plans)
        plans.sort(key = cmp_to_key(compare_plans), reverse=True)

        for i, target in enumerate(plans):

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

            unit_tag = next(
                (tag
                for tag, behavior in self.unit_manager.units.items()
                if isinstance(behavior, MacroBehavior) and behavior.plan==target), None)
            if (behavior := self.unit_manager.units.get(unit_tag)) and behavior.unit:
                positions.append(behavior.unit)

            text = f"{str(i+1)} {target.item.name}"

            for position in positions:
                self.client.debug_text_world(text, position, color=font_color, size=font_size)

            if len(positions) == 2:
                a, b = positions
                self.client.debug_line_out(a, b, color=font_color)

        font_color = (255, 0, 0)

        for enemy in self.unit_manager.enemies.values():

            if enemy.unit:
                pos = enemy.unit.position
                position = Point3((*pos, self.get_terrain_z_height(pos)))
                text = f"{enemy.unit.name}"
                self.client.debug_text_world(text, position, color=font_color, size=font_size)

        self.client.debug_text_screen(f'Threat Level: {round(100 * self.combat.threat_level)}%', (0.01, 0.01))
        self.client.debug_text_screen(f'Enemy Bases: {len(self.scout.enemy_bases)}', (0.01, 0.02))
        self.client.debug_text_screen(f'Gas Target: {round(self.resource_manager.get_gas_target(), 3)}', (0.01, 0.03))
        self.client.debug_text_screen(f'Creep Coverage: {round(100 * self.creep.coverage)}%', (0.01, 0.06))
        
        for i, plan in enumerate(plans):
            self.client.debug_text_screen(f'{1+i} {round(plan.eta or 0, 1)} {plan.item.name}', (0.01, 0.1 + 0.01 * i))

    def is_unit_missing(self, unit: UnitTypeId) -> bool:
        if unit in {
            UnitTypeId.LARVA,
            # UnitTypeId.CORRUPTOR,
            # UnitTypeId.ROACH,
            # UnitTypeId.HYDRALISK,
            # UnitTypeId.ZERGLING,
        }:
            return False
        return all(
            self.count(e, include_pending=False, include_planned=False) == 0
            for e in WITH_TECH_EQUIVALENTS[unit]
        )

    def is_upgrade_missing(self, upgrade: UpgradeId) -> bool:
        return upgrade not in self.state.upgrades

    def get_missing_requirements(self, item: MacroId) -> Iterable[MacroId]:

        if item not in REQUIREMENTS_KEYS:
            return

        if type(item) == UnitTypeId:
            trainers = UNIT_TRAINED_FROM[item]
            trainer = min(trainers, key=lambda v:v.value)
            info = TRAIN_INFO[trainer][item]
        elif type(item) == UpgradeId:
            trainer = UPGRADE_RESEARCHED_FROM[item]
            info = RESEARCH_INFO[trainer][item]

        if self.is_unit_missing(trainer):
            yield trainer
        if (
            (required_building := info.get('required_building'))
            and self.is_unit_missing(required_building)
        ):
            yield required_building
        if (
            (required_upgrade := info.get('required_upgrade'))
            and self.is_upgrade_missing(required_upgrade)
        ):
            yield required_upgrade


        # requirements.append(info.get('required_building'))
        # requirements.append(info.get('required_upgrade'))
        # requirements = [r for r in requirements if r not in { UnitTypeId.LARVA, UnitTypeId.CORRUPTOR, UnitTypeId.ROACH, UnitTypeId.ZERGLING }]
        
        # missing = set()
        # i = 0
        # while i < len(requirements):
        #     requirement = requirements[i]
        #     i += 1
        #     if not requirement:
        #         continue
        #     if type(requirement) is UnitTypeId:
        #         equivalents = WITH_TECH_EQUIVALENTS[requirement]
        #     elif type(requirement) is UpgradeId:
        #         equivalents = { requirement }
        #     else:
        #         raise TypeError()
        #     if any(self.count(e, include_pending=False, include_planned=False) for e in equivalents):
        #         continue
        #     missing.add(requirement)
        #     requirements.extend(self.get_missing_requirements(requirement))

        # return missing

    def get_owned_geysers(self):
        for base in self.resource_manager.bases:
            if not base.townhall:
                continue
            if not base.townhall.unit.is_ready:
                continue
            if base.townhall.unit.type_id not in race_townhalls[self.race]:
                continue
            for geyser in base.vespene_geysers:
                yield geyser.unit

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
        enemies = (
            unit
            for unit in self.enemies.values()
            if unit.type_id not in IGNORED_UNIT_TYPES
        )
        destructables = (
            unit
            for unit in self.destructables
            if 0 < unit.armor
        )
        if self.destroy_destructables:
            return chain(enemies, destructables)
        else:
            return enemies

    def get_unit_value(self, unit: Unit) -> float:
        health = unit.health + unit.shield
        dps =  max(unit.ground_dps, unit.air_dps)
        return math.sqrt(health * dps)

    def get_unit_cost(self, unit_type: UnitTypeId) -> int:
        cost = self.calculate_unit_value(unit_type)
        return cost.minerals + cost.vespene

    def get_max_harvester(self) -> int:
        workers = 0
        workers += sum((b.harvester_target for b in self.resource_manager.bases_taken))
        workers += 16 * self.count(UnitTypeId.HATCHERY, include_actual=False, include_planned=False)
        workers += 3 * self.count(GAS_BY_RACE[self.race], include_actual=False, include_planned=False)
        return workers

    def blocked_bases(self, position: Point2, margin: float = 0.0) -> Iterable[Base]:
        px, py = position
        radius = 3
        for base in self.resource_manager.bases:
            bx, by = base.position
            if abs(px - bx) < margin + radius and abs(py - by) < margin + radius:
                yield base