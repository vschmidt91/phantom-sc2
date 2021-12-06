
from abc import ABC
from collections import defaultdict
from enum import Enum
from functools import reduce
from json import detect_encoding
import math
import random
from typing import DefaultDict, Iterable, Optional, Tuple, Union, Coroutine, Set, List, Callable, Dict
import numpy as np
from s2clientprotocol.data_pb2 import Weapon
from s2clientprotocol.raw_pb2 import Effect
from s2clientprotocol.sc2api_pb2 import Macro
from scipy import ndimage
from s2clientprotocol.common_pb2 import Point
from s2clientprotocol.error_pb2 import Error
from queue import Queue
import os
from sc2 import position

from MapAnalyzer.MapData import MapData

from sc2.game_state import ActionRawUnitCommand
from sc2.ids.effect_id import EffectId
from sc2 import game_info, game_state
from sc2.position import Point2, Point3
from sc2.bot_ai import BotAI
from sc2.constants import IS_DETECTOR, SPEED_INCREASE_ON_CREEP_DICT, IS_STRUCTURE
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
from sc2.unit import Unit
from sc2.unit_command import UnitCommand
from sc2.units import Units

from .resources.base import Base
from .resources.resource_group import ResourceGroup
from .behaviors.dodge import *
from .behaviors.unit_manager import UnitManager
from .constants import *
from .macro_plan import MacroPlan
from .cost import Cost
from .utils import *
import suntzu.behaviors.dodge as dodge

import matplotlib.pyplot as plt

from .enums import PerformanceMode

class PlacementNotFound(Exception):
    pass

class AIBase(ABC, BotAI):

    def __init__(self,
        game_step: Optional[int] = None,
        debug: bool = False,
        performance: PerformanceMode = PerformanceMode.DEFAULT,
    ):
        self.tags: List[str] = list()
        self.game_step: Optional[int] = game_step
        self.performance: PerformanceMode = performance
        self.debug: bool = debug
        self.raw_affects_selection = True
        self.greet_enabled: bool = True
        self.macro_plans = list()
        self.composition: Dict[UnitTypeId, int] = dict()
        self.worker_split: Dict[int, int] = None
        self.cost: Dict[MacroId, Cost] = dict()
        self.bases: ResourceGroup[Base] = None
        self.enemy_positions: Optional[Dict[int, Point2]] = dict()
        self.dodge_delayed: List[dodge.DodgeEffectDelayed] = list()
        self.distance_map: np.ndarray = None
        self.threat_level: float = 0.0
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
        self.planned_by_type: DefaultDict[MacroId, Set[MacroPlan]] = defaultdict(lambda:set())
        self.worker_supply_fixed: int = 0
        self.destructables_fixed: Set[Unit] = set()
        self.damage_taken: Dict[int] = dict()
        self.gg_sent: bool = False
        self.unit_ref: Optional[int] = None
        self.dodge_map: np.ndarray = None
        self.dodge_gradient_map: np.ndarray = None
        self.abilities: DefaultDict[int, Set[AbilityId]] = defaultdict(lambda:set())
        self.map_analyzer: MapData = None
        self.army_center: Point2 = Point2((0, 0))
        self.enemy_base_count: int = 1
        self.army_influence_map: np.ndarray = None
        self.enemy_influence_map: np.ndarray = None
        self.unit_manager: UnitManager = UnitManager(self)
        self.tumor_front_tags: Set[int] = set()

    @property
    def plan_units(self) -> List[int]:
        return [
            plan.unit for plan in self.macro_plans
            if plan.unit
        ]

    @property
    def tumor_front(self) -> Iterable[Unit]:
        return (self.unit_by_tag[t] for t in self.tumor_front_tags)

    @property
    def is_speedmining_enabled(self) -> bool:
        if self.performance is PerformanceMode.DEFAULT:
            return True
        elif self.performance is PerformanceMode.HIGH_PERFORMANCE:
            return False
        raise Exception

    def estimate_enemy_velocity(self, unit: Unit) -> Point2:
        previous_position = self.enemy_positions.get(unit.tag, unit.position)
        velocity = unit.position - previous_position * 22.4 / (self.client.game_step)
        return velocity

    def destroy_destructables(self):
        return True

    async def on_before_start(self):

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

        self.map_analyzer = MapData(self)
        self.enemy_map = self.map_analyzer.get_pyastar_grid()
        self.friend_map = self.map_analyzer.get_pyastar_grid()

        await self.create_distance_map()
        await self.initialize_bases()

    def handle_errors(self):
        for error in self.state.action_errors:
            if error.result == ActionResult.CantBuildLocationInvalid.value:
                item = UNIT_BY_TRAIN_ABILITY.get(error.exact_id)
                if not item:
                    continue
                plan = next((
                    plan
                    for plan in self.macro_plans
                    if plan.item == item and plan.unit == error.unit_tag
                ), None)
                if not plan:
                    continue
                if item in race_townhalls[self.race] and plan.target:
                    base = min(self.bases, key = lambda b : b.position.distance_to(plan.target))
                    if not base.blocked_since:
                        base.blocked_since = self.time
                plan.target = None

    def units_detecting(self, unit) -> Iterable[Unit]:
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
            item = UNIT_BY_TRAIN_ABILITY.get(action.exact_id) or UPGRADE_BY_RESEARCH_ABILITY.get(action.exact_id)
            if not item:
                continue
            for unit_tag in action.unit_tags:
                unit = self.unit_by_tag.get(unit_tag)
                if not unit:
                    continue
                if not unit.is_structure and self.is_structure(item):
                    continue
                plan = next((
                    plan
                    for plan in self.macro_plans
                    if plan.item == item
                ), None)
                if not plan:
                    continue
                self.remove_macro_plan(plan)

    def reset_blocked_bases(self):
        for base in self.bases:
            if base.blocked_since:
                if base.blocked_since + 30 < self.time:
                    base.blocked_since = None

    def handle_delayed_effects(self):

        self.dodge_delayed = [
            d
            for d in self.dodge_delayed
            if self.time < self.dodge_delayed[0].time + self.dodge_delayed[0].delay
        ]

    def enumerate_army(self) -> Iterable[Unit]:
        for unit in self.units:
            if unit.type_id not in CIVILIANS:
                yield unit
            elif unit.tag in self.unit_manager.drafted_civilians:
                yield unit

    async def greet_opponent(self):
        if 1 < self.time and self.greet_enabled:
            for tag in self.tags:
                await self.client.chat_send('Tag:' + tag, True)
            self.greet_enabled = False

    async def on_step(self, iteration: int):
        if self.state.game_loop % 100 == 0:
            print(f'{self.time_formatted} Threat Level: {round(self.threat_level, 3)}')
        pass

    async def on_end(self, game_result: Result):
        pass

    async def on_building_construction_started(self, unit: Unit):
        plan = next((
            plan
            for plan in self.macro_plans
            if plan.item == unit.type_id
        ), None)
        if plan:
            self.remove_macro_plan(plan)
        self.pending_by_type[unit.type_id].add(unit)

    async def on_building_construction_complete(self, unit: Unit):
        if unit.type_id in race_townhalls[self.race]:
            base = next((b for b in self.bases if b.position == unit.position), None)
            if base:
                base.townhall = unit.tag
        pass

    async def on_enemy_unit_entered_vision(self, unit: Unit):
        pass

    async def on_enemy_unit_left_vision(self, unit_tag: int):
        pass

    async def on_unit_created(self, unit: Unit):
        pass

    async def on_unit_destroyed(self, unit_tag: int):
        self.enemies.pop(unit_tag, None)
        self.bases.try_remove(unit_tag)
        self.tumor_front_tags.difference_update((unit_tag,))
        pass

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float):
        if unit.is_structure and not unit.is_ready:
            should_cancel = False
            # if self.performance is PerformanceMode.DEFAULT:
            #     potential_damage = 0
            #     for enemy in self.all_enemy_units:
            #         damage, speed, range = enemy.calculate_damage_vs_target(unit)
            #         if unit.position.distance_to(enemy.position) <= unit.radius + range + enemy.radius:
            #             potential_damage += damage
            #     if unit.health + unit.shield <= potential_damage:
            #         should_cancel = True
            # else:
            if unit.shield_health_percentage < 0.1:
                should_cancel = True
            if should_cancel:
                unit(AbilityId.CANCEL)
        self.damage_taken[unit.tag] = self.time
        pass
        
    async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId):
        pass

    async def on_upgrade_complete(self, upgrade: UpgradeId):
        pass

    async def kill_random_unit(self):
        chance = self.supply_used / 200
        chance = pow(chance, 3)
        exclude = { self.townhalls[0].tag } if self.townhalls else set()
        if chance < random.random():
            unit = self.all_own_units.tags_not_in(exclude).random
            await self.client.debug_kill_unit(unit)

    def count(self,
        item: MacroId,
        include_pending: bool = True,
        include_planned: bool = True,
        include_actual: bool = True
    ) -> int:

        factor = 2 if item == UnitTypeId.ZERGLING else 1
        
        sum = 0
        if include_actual:
            if item in WORKERS and self.worker_supply_fixed is not None:
                sum += self.worker_supply_fixed
                # fix worker count (so that it includes workers in gas buildings)
                # sum += self.supply_used - self.supply_army - len(self.pending_by_type[item])
            else:
                sum += len(self.actual_by_type[item])
        if include_pending:
            sum += factor * len(self.pending_by_type[item])
        if include_planned:
            sum += factor * len(self.planned_by_type[item])

        return sum

    async def update_tables(self):

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
            elif self.is_visible(enemy.position):
                # could see, but not there
                continue
            # cannot see, maybe still there
            self.enemies[tag] = enemy

        self.enemies_by_type.clear()
        for enemy in self.enemies.values():
            self.enemies_by_type[enemy.type_id].add(enemy)
        
        self.resource_by_position.clear()
        self.gas_building_by_position.clear()
        self.unit_by_tag.clear()
        self.townhall_by_position.clear()
        self.actual_by_type.clear()
        self.pending_by_type.clear()
        self.destructables_fixed.clear()
        self.worker_supply_fixed = None

        for townhall in self.townhalls.ready:
            self.townhall_by_position[townhall.position] = townhall
        
        for unit in self.all_own_units:
            self.unit_by_tag[unit.tag] = unit
            if unit.is_ready:
                self.actual_by_type[unit.type_id].add(unit)
            else:
                self.pending_by_type[unit.type_id].add(unit)
            for order in unit.orders:
                ability = order.ability.exact_id
                training = UNIT_BY_TRAIN_ABILITY.get(ability) or UPGRADE_BY_RESEARCH_ABILITY.get(ability)
                if training and (unit.is_structure or not self.is_structure(training)):
                    self.pending_by_type[training].add(unit)

        for unit in self.resources:
            self.resource_by_position[unit.position] = unit
        for gas in self.gas_buildings:
            self.gas_building_by_position[gas.position] = gas

        for unit in self.destructables:
            if 0 < unit.armor:
                self.destructables_fixed.add(unit)


        for upgrade in self.state.upgrades:
            self.actual_by_type[upgrade].add(upgrade)

        worker_type = race_worker[self.race]
        worker_pending = self.count(worker_type, include_actual=False, include_pending=False, include_planned=False)
        self.worker_supply_fixed = self.supply_used - self.supply_army - worker_pending

        unit_abilities = await self.get_available_abilities(self.all_own_units)
        self.abilities = {
            unit.tag: set(abilities)
            for unit, abilities in zip(self.all_own_units, unit_abilities)
        }

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
        for enemy in self.enemies.values():
            self.enemy_positions[enemy.tag] = enemy.position

    def make_composition(self):
        if self.supply_used == 200:
            return
        composition_have = {
            unit: self.count(unit)
            for unit in self.composition.keys()
        }
        for unit, count in self.composition.items():
            if count < 1:
                continue
            elif count <= composition_have[unit]:
                continue
            if any(self.get_missing_requirements(unit, include_pending=False, include_planned=False)):
                continue
            priority = -self.count(unit, include_planned=False) /  count
            plans = self.planned_by_type[unit]
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
        gas_have = self.count(UnitTypeId.EXTRACTOR)
        gas_max = sum(1 for g in self.get_owned_geysers())
        gas_want = min(gas_max, gas_depleted + math.ceil(gas_target / 3))
        if gas_have < gas_want:
            self.add_macro_plan(MacroPlan(UnitTypeId.EXTRACTOR, priority=1))

    def get_gas_target(self):
        cost_zero = Cost(0, 0, 0)
        cost_sum = sum((plan.cost or self.cost[plan.item] for plan in self.macro_plans), cost_zero)
        cs = [self.cost[unit] * max(0, count - self.count(unit, include_planned=False)) for unit, count in self.composition.items()]
        cost_sum += sum(cs, cost_zero)
        minerals = max(0, cost_sum.minerals - self.minerals)
        vespene = max(0, cost_sum.vespene - self.vespene)
        if 7 * 60 < self.time and (minerals + vespene) == 0:
            gas_ratio = 6 / 22
        else:
            gas_ratio = vespene / max(1, vespene + minerals)
        worker_type = race_worker[self.race]
        gas_target = gas_ratio * self.count(worker_type, include_planned=False, include_pending=False)
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

        for base in self.bases:
            base.defensive_units.clear()
            base.defensive_units_planned.clear()

        for unit_type in STATIC_DEFENSE[self.race]:
            for unit in chain(self.actual_by_type[unit_type], self.pending_by_type[unit_type]):
                base = min(self.bases, key=lambda b:b.position.distance_to(unit.position))
                base.defensive_units.add(unit)
            for plan in self.planned_by_type[unit_type]:
                if not isinstance(plan.target, Point2):
                    continue
                base = min(self.bases, key=lambda b:b.position.distance_to(plan.target))
                base.defensive_units_planned.add(plan)

        self.bases.update(self)

    async def initialize_bases(self):

        bases = sorted((
            Base(position, (m.position for m in resources.mineral_field), (g.position for g in resources.vespene_geyser))
            for position, resources in self.expansion_locations_dict.items()
        ), key = lambda b : self.distance_map[b.position.rounded] - .5 * b.position.distance_to(self.enemy_start_locations[0]) / self.game_info.map_size.length)

        self.bases = ResourceGroup(bases)
        self.bases[0].split_initial_workers(set(self.workers))
        self.bases[-1].taken_since = 1

    async def create_distance_map(self):

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

        self.distance_map = distance_map

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
                unit = self.unit_by_tag.get(target.unit)
                if unit:
                    positions.append(unit)

            text = f"{str(i+1)} {str(target.item.name)}"

            for position in positions:
                self.client.debug_text_world(
                    text,
                    position,
                    color=font_color,
                    size=font_size)

        # for d in self.enemies.values():
        #     z = self.get_terrain_z_height(d)
        #     self.client.debug_text_world(f'{d.health}', Point3((*d.position, z)))

        self.client.debug_text_screen(f'Threat Level: {round(100 * self.threat_level)}%', (0.01, 0.01))
        self.client.debug_text_screen(f'Enemy Bases: {self.enemy_base_count}', (0.01, 0.02))
        for i, plan in enumerate(self.macro_plans):
            self.client.debug_text_screen(f'{1+i} {plan.item.name}', (0.01, 0.1 + 0.01 * i))

        # for p, d in np.ndenumerate(self.distance_map):
        #     z = self.get_terrain_z_height(Point2(p))
        #     advantage_defender = (1 - self.distance_map[p]) / max(1e-3, self.power_level)
        #     self.client.debug_text_world(f'{round(100 * advantage_defender)}', Point3((*p, z)))

        # for base in self.bases:
        #     for patch in base.mineral_patches:
        #         if not patch.speed_mining_position:
        #             continue
        #         p = patch.speed_mining_position
        #         z = self.get_terrain_z_height(p)
        #         c = (255, 255, 255)
        #         self.client.debug_text_world(f'x', Point3((*p, z)), c)

        # for p, v in np.ndenumerate(self.heat_map):
        #     if not self.in_pathing_grid(Point2(p)):
        #         continue
        #     z = self.get_terrain_z_height(Point2(p))
        #     c = int(255 * v)
        #     c = (c, 255 - c, 0)
        #     self.client.debug_text_world(f'{round(100 * v)}', Point3((*p, z)), c)

        # for p, v in np.ndenumerate(self.enemy_map_blur):
        #     if v == 0:
        #         continue
        #     if not self.in_pathing_grid(Point2(p)):
        #         continue
        #     z = self.get_terrain_z_height(Point2(p))
        #     c = (255, 255, 255)
        #     self.client.debug_text_world(f'{round(v)}', Point3((*p, z)), c)

    async def time_to_reach(self, unit, target):
        if isinstance(target, Unit):
            position = target.position
        elif isinstance(target, Point2):
            position = target
        else:
            raise TypeError()
        path = await self.client.query_pathing(unit.position, target.position)
        if not path:
            path = unit.position.distance_to(position)
        movement_speed = 1.4 * unit.movement_speed
        if movement_speed == 0:
            if self.debug:
                raise Exception()
            else:
                return 0
        return path / movement_speed

    def add_macro_plan(self, plan: MacroPlan):
        self.macro_plans.append(plan)
        self.planned_by_type[plan.item].add(plan)

    def remove_macro_plan(self, plan: MacroPlan):
        self.macro_plans.remove(plan)
        self.planned_by_type[plan.item].remove(plan)

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
        requirements = [r for r in requirements if r is not UnitTypeId.LARVA]
        
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

    async def macro(self):

        reserve = Cost(0, 0, 0)
        exclude = { o.unit for o in self.macro_plans }
        exclude.update(unit.tag for units in self.pending_by_type.values() for unit in units)
        exclude.update(self.unit_manager.drafted_civilians)
        self.macro_plans.sort(key = lambda t : t.priority, reverse=True)

        for plan in self.macro_plans:

            if (
                any(self.get_missing_requirements(plan.item, include_pending=False, include_planned=False))
                and plan.priority < BUILD_ORDER_PRIORITY
            ):
                continue

            cost = plan.cost or self.cost[plan.item]
            can_afford = self.can_afford_with_reserve(cost, reserve)

            if plan.item == UnitTypeId.NOTAUNIT:
                reserve += cost
                continue

            unit = None
            if plan.unit:
                unit = self.unit_by_tag.get(plan.unit)
            if not unit:
                unit, plan.ability = self.search_trainer(plan.item, exclude=exclude)
            if not unit:
                continue
            if not plan.ability:
                plan.unit = None
                continue
            if any(o.ability.exact_id == plan.ability['ability'] for o in unit.orders):
                continue
            
            # if not can_afford:
            #     minerals_surplus = max(0, self.minerals - reserve.minerals)
            #     vespene_surplus = max(0, self.vespene - reserve.vespene)
            #     minerals_needed = max(0, cost.minerals - minerals_surplus)
            #     vespene_needed = max(0, cost.vespene - vespene_surplus)
            #     time_minerals = minerals_needed / max(1, income_minerals)
            #     time_vespene = vespene_needed / max(1, income_vespene)
            #     time_to_harvest =  max(time_minerals, time_vespene)

            #     if time_minerals < time_vespene:
            #         minerals_reserve = minerals_needed * time_minerals / time_vespene

            #     minerals_needed = min(cost.minerals, minerals_surplus + round(time_to_harvest * income_minerals))
            #     vespene_needed = min(cost.vespene, vespene_surplus + round(time_to_harvest * income_vespene))
                
            #     cost = Cost(minerals_needed, vespene_needed, cost.food)
            reserve += cost

            if unit.type_id != UnitTypeId.LARVA:
                plan.unit = unit.tag
            exclude.add(plan.unit)

            if plan.target is None:
                try:
                    plan.target = await self.get_target(unit, plan)
                except PlacementNotFound as p: 
                    continue

            # if isinstance(plan.target, Unit):
            #     plan.target = self.unit_by_tag.get(plan.target.tag)
            #     if not plan.target:
            #         continue

            if any(self.get_missing_requirements(plan.item, include_pending=False, include_planned=False)):
                continue

            if (
                plan.target
                and not unit.is_moving
                and 0 < unit.movement_speed
                and 1 < unit.position.distance_to(plan.target)
            ):
            
                time = await self.time_to_reach(unit, plan.target)
                
                minerals_needed = reserve.minerals - self.minerals
                vespene_needed = reserve.vespene - self.vespene
                time_minerals = 60 * minerals_needed / max(1, self.state.score.collection_rate_minerals)
                time_vespene = 60 * vespene_needed / max(1, self.state.score.collection_rate_vespene)
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
                    target2 = await self.find_placement(plan.item, plan.target, max_distance=plan.max_distance or 20)
                    if not target2:
                        continue
                    plan.target = target2

            queue = False
            if unit.is_carrying_resource:
                unit.return_resource()
                queue = True

            if not unit(plan.ability["ability"], target=plan.target, queue=queue, subtract_cost=True):
                if self.debug:
                    print("objective failed:" + str(plan))
                    raise Exception()


    def get_owned_geysers(self):
        for base in self.bases:
            if base.position not in self.townhall_by_position.keys():
                continue
            for gas in base.vespene_geysers:
                geyser = self.resource_by_position.get(gas.position)
                if not geyser:
                    continue
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
                for trainer in self.pending_by_type[gas_type]
                for order in trainer.orders
                if isinstance(order.target, int)
            }
            exclude_tags.update({
                step.target.tag
                for step in self.planned_by_type[gas_type]
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
            
            position = await self.find_placement(objective.ability["ability"], position, max_distance=objective.max_distance or 20, placement_step=1, addon_place=withAddon)
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
            for trainer in self.actual_by_type[trainer_type]
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

    def get_unit_range(self, unit: Unit, ground: bool = True, air: bool = True) -> float:

        unit_range = 0
        if ground:
            unit_range = max(unit_range, unit.ground_range)
        if air:
            unit_range = max(unit_range, unit.air_range)

        range_upgrades = RANGE_UPGRADES.get(unit.type_id)
        if range_upgrades:
            if unit.is_mine:
                range_boni = (v for u, v in range_upgrades.items() if u in self.state.upgrades)
            elif unit.is_enemy:
                range_boni = range_upgrades.values()
            unit_range += sum(range_boni)

        return unit_range

    def enumerate_enemies(self) -> Iterable[Unit]:
        enemies = list(self.enemies.values())
        if self.destroy_destructables():
            enemies.extend(self.destructables_fixed)
        enemies = [
            e for e in enemies
            if e.type_id not in { UnitTypeId.LARVA, UnitTypeId.EGG }
        ]
        return enemies

    async def micro(self):
        pass

    async def get_target_position(self, target: UnitTypeId, trainer: Unit) -> Point2:
        if self.is_structure(target):
            if target in race_townhalls[self.race]:
                for b in self.bases:
                    if b.position in self.townhall_by_position.keys():
                        continue
                    if b.blocked_since:
                        continue
                    # if not b.remaining:
                    #     continue
                    if not await self.can_place_single(target, b.position):
                        continue
                    return b.position
                raise PlacementNotFound()
            elif self.townhalls.exists:
                position = self.townhalls.closest_to(self.start_location).position
                return position.towards(self.game_info.map_center, 6)
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

    def is_structure(self, unit: MacroId) -> bool:
        if type(unit) is not UnitTypeId:
            return False
        data = self.game_data.units.get(unit.value)
        if data is None:
            return False
        return IS_STRUCTURE in data.attributes

    def get_supply_buffer(self) -> int:
        buffer = 4
        buffer += 1 * self.townhalls.amount
        buffer += 3 * self.count(UnitTypeId.QUEEN, include_pending=False, include_planned=False)
        return buffer

    def get_unit_value(self, unit: Unit) -> float:
        if unit.is_burrowed:
            return 0
        if not unit.is_ready:
            return 0
        cost = self.calculate_unit_value(unit.type_id)
        return cost.minerals + cost.vespene

    def update_maps(self):

        enemy_influence_map = self.map_analyzer.get_pyastar_grid()
        for enemy in self.enemies.values():
            enemy_range = max(0.5 * enemy.movement_speed, self.get_unit_range(enemy))
            self.enemy_influence_map = self.map_analyzer.add_cost(
                position = enemy.position,
                radius = enemy.radius + enemy_range,
                grid = enemy_influence_map,
                weight = self.get_unit_value(enemy),
            )
        self.enemy_influence_map = enemy_influence_map

        army_influence_map = self.map_analyzer.get_pyastar_grid()
        for unit in self.enumerate_army():
            unit_range = max(0.5 * unit.movement_speed, self.get_unit_range(unit))
            self.army_influence_map = self.map_analyzer.add_cost(
                position = unit.position,
                radius = unit.radius + unit_range,
                grid = army_influence_map,
                weight = self.get_unit_value(unit),
            )
        self.army_influence_map = army_influence_map

        dodge: List[DodgeElement] = list()
        delayed_positions = { e.position for e in self.dodge_delayed }
        for effect in self.state.effects:
            if effect.id in DODGE_DELAYED_EFFECTS:
                dodge_effect = DodgeEffectDelayed(effect, self.time)
                if dodge_effect.position in delayed_positions:
                    continue
                self.dodge_delayed.append(dodge_effect)
            elif effect.id in DODGE_EFFECTS:
                dodge.append(DodgeEffect(effect))
        for type in DODGE_UNITS:
            for enemy in self.enemies_by_type[type]:
                dodge.append(DodgeUnit(enemy))
        dodge.extend(self.dodge_delayed)

        dodge_map = self.map_analyzer.get_pyastar_grid()
        for element in dodge:
            dodge_map = element.add_damage(self.map_analyzer, dodge_map, self.time)
        self.dodge_map = dodge_map

            # movement_speed = 1 # assume speed of Queens on creep
            # if isinstance(dodge, DodgeEffectDelayed):
            #     time_to_impact = max(0, dodge.time_of_impact - self.time)
            # else:
            #     time_to_impact = 0
            # dodge_radius = dodge.radius + 2 - time_to_impact * movement_speed
            # if dodge_radius <= 0:
            #     continue

            # for position in dodge.positions:
            #     dodge_map = self.map_analyzer.add_cost(
            #         position = position,
            #         radius = dodge_radius,
            #         grid = dodge_map,
            #         weight = 1000
            #     )

        # dodge_blur_map = ndimage.gaussian_filter(dodge_map, 5)
        # dodge_gradient_map = np.dstack(np.gradient(dodge_blur_map))
        # self.dodge_gradient_map = dodge_gradient_map

        # self.enemy_influence_map = np.where(np.isposinf(self.enemy_influence_map), 0, self.enemy_influence_map)
        # self.army_influence_map = np.where(np.isposinf(self.army_influence_map), 0, self.army_influence_map)
        
        # blur_sigma = 4
        # self.enemy_influence_map = ndimage.gaussian_filter(self.enemy_influence_map, blur_sigma)
        # self.army_influence_map = ndimage.gaussian_filter(self.army_influence_map, blur_sigma)

        # self.map_analyzer.draw_influence_in_game(dodge_map)

    def assess_threat_level(self):

        army = list(self.enumerate_army())

        value_self = sum(self.get_unit_value(u) for u in self.enumerate_army())
        value_enemy = sum(self.get_unit_value(e) for e in self.enemies.values())
        value_enemy_threats = sum(self.get_unit_value(e) * (1 - self.distance_map[e.position.rounded]) for e in self.enemies.values())

        self.power_level = value_enemy / max(1, value_self + value_enemy)
        self.threat_level = value_enemy_threats / max(1, value_self + value_enemy_threats)


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
        workers += 16 * self.count(UnitTypeId.HATCHERY, include_actual=False, include_planned=False)
        return workers

    def blocked_base(self, position: Point2) -> Optional[Point]:
        px, py = position
        radius = 3
        for base in self.expansion_locations_list:
            bx, by = base
            if abs(px - bx) < radius and abs(py - by) < radius:
                return base
        return None