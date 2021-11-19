
from collections import defaultdict
from enum import Enum
from functools import reduce
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
from sc2.data import Result, race_townhalls, race_worker, ActionResult
from sc2.unit import Unit
from sc2.units import Units
from suntzu.tactics.unit_single import UnitSingle

from .analysis.poisson_solver import solve_poisson, solve_poisson_full
from .resources.vespene_geyser import VespeneGeyser
from .resources.base import Base
from .resources.mineral_patch import MineralPatch
from .resources.resource_base import ResourceBase
from .resources.resource_group import T, ResourceGroup
from .constants import *
from .macro_plan import MacroPlan
from .cost import Cost
from .utils import *
from .corrosive_bile import CorrosiveBile

MacroId = Union[UnitTypeId, UpgradeId]
 
DODGE_EFFECTS = {
    # EffectId.THERMALLANCESFORWARD,
    EffectId.LURKERMP,
    EffectId.NUKEPERSISTENT,
    # EffectId.RAVAGERCORROSIVEBILECP,
    EffectId.PSISTORMPERSISTENT,
    # EffectId.LIBERATORTARGETMORPHPERSISTENT,
    # EffectId.LIBERATORTARGETMORPHDELAYPERSISTENT,
}

DODGE_UNITS = {
    UnitTypeId.DISRUPTORPHASED,
    UnitTypeId.WIDOWMINEWEAPON,
    UnitTypeId.WIDOWMINEAIRWEAPON,
    UnitTypeId.NUKE,
    UnitTypeId.BANELING,
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
        self.worker_split: Dict[int, int] = None
        self.cost: Dict[MacroId, Cost] = dict()
        self.bases: ResourceGroup[Base] = None
        self.enemy_positions: Optional[Dict[int, Point2]] = dict()
        self.corrosive_biles: List[CorrosiveBile] = list()
        self.enemy_map: np.ndarray = None
        self.enemy_gradient_map: np.ndarray = None
        self.friend_map: np.ndarray = None
        self.threat_map: np.ndarray = None
        self.distance_map: np.ndarray = None
        self.distance_gradient_map: np.ndarray = None
        self.threat_level = 0
        self.enemies: Dict[int, Unit] = dict()
        self.enemies_by_type: DefaultDict[UnitTypeId, Set[Unit]] = defaultdict(lambda:set())
        self.weapons: Dict[UnitTypeId, List] = dict()
        self.dps: Dict[UnitTypeId, float] = dict()
        self.potentially_dead_harvesters: Dict[int, int] = dict()
        self.resource_by_position: Dict[Point2, Unit] = dict()
        self.unit_by_tag: Dict[int, Unit] = dict()
        self.actual_by_type: DefaultDict[MacroId, Set[Unit]] = defaultdict(lambda:set())
        self.pending_by_type: DefaultDict[MacroId, Set[Unit]] = defaultdict(lambda:set())
        self.planned_by_type: DefaultDict[MacroId, Set[MacroPlan]] = defaultdict(lambda:set())
        self.worker_supply_fixed: int = 0
        self.destructables_fixed: Set[Unit] = set()
        self.drafted_civilians: Set[int] = set()
        self.damage_taken: Dict[int] = dict()
        self.gg_sent: bool = False
        self.unit_ref: Optional[int] = None

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
        self.townhalls[0](AbilityId.RALLY_WORKERS, target=self.townhalls[0])
        self.enemy_map = np.zeros(self.game_info.map_size)
        self.enemy_gradient_map = np.zeros([*self.game_info.map_size, 2])
        self.friend_map = np.zeros(self.game_info.map_size)
        await self.create_distance_map()
        await self.initialize_bases()

        # await self.client.debug_show_map()

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
                if item in race_townhalls[self.race]:
                    base = min(self.bases, key = lambda b : b.position.distance_to(plan.target))
                    if not base.blocked_since:
                        base.blocked_since = self.time
                plan.target = None

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
                # unit = self.unit_by_tag.get(unit_tag)
                # if not unit:
                #     continue
                # self.pending_by_type[item].add(unit)

    def reset_blocked_bases(self):
        for base in self.bases:
            if not base.blocked_since:
                continue
            if base.blocked_since + 60 < self.time:
                base.blocked_since = None

    def handle_corrosive_biles(self):
        bile_positions = { c.position for c in self.corrosive_biles }
        for effect in self.state.effects:
            if effect.id != EffectId.RAVAGERCORROSIVEBILECP:
                continue
            position = next(iter(effect.positions))
            if position in bile_positions:
                continue
            bile = CorrosiveBile(self.state.game_loop, position)
            self.corrosive_biles.append(bile)

        # biles_sorted = sorted(self.corrosive_biles, key = lambda c : c.frame_expires)
        # assert(self.corrosive_biles == biles_sorted)

        while (
            self.corrosive_biles
            and self.corrosive_biles[0].frame_expires <= self.state.game_loop
        ):
            self.corrosive_biles.pop(0)

    def assign_idle_workers(self):
        exclude = set()
        exclude.update(self.bases.harvesters)
        exclude.update(p.unit for p in self.macro_plans)
        exclude.update(self.drafted_civilians)
        for worker in self.workers.tags_not_in(exclude):
            base = min(self.bases, key = lambda b : worker.distance_to(b.position))
            base.try_add(worker.tag)

    async def greet_opponent(self):
        if 1 < self.time and self.greet_enabled:
            for tag in self.tags:
                await self.client.chat_send('Tag:' + tag, True)
            self.greet_enabled = False

    async def on_step(self, iteration: int):
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
        self.enemies.pop(unit_tag, None)
        self.bases.try_remove(unit_tag)
        pass

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float):
        if unit.is_structure:
            if self.performance == PerformanceMode.DEFAULT:
                potential_damage = 0
                for enemy in self.all_enemy_units:
                    damage, speed, range = enemy.calculate_damage_vs_target(unit)
                    if  unit.distance_to(enemy) < unit.radius + range + enemy.radius:
                        potential_damage += damage
                if unit.health + unit.shield <= potential_damage:
                    if self.structures.amount == 1:
                        if not self.gg_sent:
                            await self.client.chat_send('gg', False)
                            self.gg_sent = True
                    if not unit.is_ready:
                        unit(AbilityId.CANCEL)
            else:
                if unit.shield_health_percentage < 0.1:
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

    def update_tables(self):

        enemies_remembered = self.enemies.copy()
        self.enemies = {
            enemy.tag: enemy
            for enemy in self.all_enemy_units
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
        self.unit_by_tag.clear()
        self.actual_by_type.clear()
        self.pending_by_type.clear()
        self.destructables_fixed.clear()
        self.worker_supply_fixed = None
        
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
            self.unit_by_tag[unit.tag] = unit
            if unit.is_mineral_field:
                self.resource_by_position[unit.position] = unit
            elif unit.is_vespene_geyser:
                if unit.type_id is not GAS_BY_RACE[self.race]:
                    self.resource_by_position[unit.position] = unit

        for unit in self.destructables:
            self.unit_by_tag[unit.tag] = unit
            if 0 < unit.armor:
                self.destructables_fixed.add(unit)


        for upgrade in self.state.upgrades:
            self.actual_by_type[upgrade].add(upgrade)

        worker_type = race_worker[self.race]
        worker_pending = self.count(worker_type, include_actual=False, include_pending=False, include_planned=False)
        self.worker_supply_fixed = self.supply_used - self.supply_army - worker_pending

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
            priority = -composition_have[unit] /  count
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
        cost_sum = sum((self.cost[plan.item] or cost_zero for plan in self.macro_plans), cost_zero)
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
                base = min(self.bases, key=lambda b:b.position.distance_to(unit))
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
        ), key = lambda b : self.distance_map[b.position.rounded] - .3 * b.position.distance_to(self.enemy_start_locations[0]) / self.game_info.map_size.length)

        self.bases = ResourceGroup(bases)
        self.bases.items[0].mineral_patches.do_worker_split(set(self.workers))

        if self.performance == PerformanceMode.DEFAULT:
            for base in self.bases:
                for minerals in base.mineral_patches:
                    minerals.speed_mining_enabled = True

    async def create_distance_map(self):
        distance_map = 0.5 * np.ones(self.game_info.map_size)
        paths_self = await self.client.query_pathings([
            [self.start_location, Point2(p)]
            for p, _ in np.ndenumerate(distance_map)
        ])
        paths_enemy = await self.client.query_pathings([
            [self.enemy_start_locations[0], Point2(p)]
            for p, _ in np.ndenumerate(distance_map)
        ])
        for (p, _), p1, p2 in zip(np.ndenumerate(distance_map), paths_self, paths_enemy):
            if not self.in_pathing_grid(Point2(p)):
                continue
            if p1 == p2 == 0:
                continue
            distance_map[p] = p1 / (p1 + p2)
        distance_map[self.start_location.rounded] = 0.0
        distance_map[self.enemy_start_locations[0].rounded] = 1.0

        self.distance_map = distance_map
        self.distance_gradient_map = np.stack(np.gradient(distance_map), axis=2)
        gradient_norm = np.linalg.norm(self.distance_gradient_map, axis=2)
        gradient_norm = np.maximum(gradient_norm, 1e-5)
        gradient_norm = np.dstack((gradient_norm, gradient_norm))
        self.distance_gradient_map = self.distance_gradient_map / gradient_norm

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
        #     self.client.debug_text_world(f'{d.is_flying} {d.is_structure}', Point3((*d.position, z)))

        self.client.debug_text_screen(f'Threat Level: {round(100 * self.threat_level)}%', (0.01, 0.01))
        for i, plan in enumerate(self.macro_plans):
            self.client.debug_text_screen(f'{1+i} {plan.item.name}', (0.01, 0.1 + 0.01 * i))

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

    @property
    def income(self):
        income_minerals = sum(base.mineral_patches.income for base in self.bases)
        income_vespene = sum(base.vespene_geysers.income for base in self.bases)
        return income_minerals, income_vespene

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
        exclude.update(self.drafted_civilians)
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
            
            reserve += cost

            if unit.type_id != UnitTypeId.LARVA:
                plan.unit = unit.tag
            exclude.add(plan.unit)

            if plan.target is None:
                try:
                    plan.target = await self.get_target(unit, plan)
                except PlacementNotFound as p: 
                    continue

            if isinstance(plan.target, Unit):
                plan.target = self.unit_by_tag.get(plan.target.tag)
                if not plan.target:
                    continue

            if any(self.get_missing_requirements(plan.item, include_pending=False, include_planned=False)):
                continue

            if (
                plan.target
                and not unit.is_moving
                and unit.movement_speed
                and 1 < unit.distance_to(plan.target)
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
                    target2 = await self.find_placement(plan.item, plan.target, max_distance=plan.max_distance or 20)
                    if not target2:
                        continue
                    plan.target = target2

            # if took_action and plan.priority == BUILD_ORDER_PRIORITY:
            #     continue

            queue = False
            if unit.is_carrying_resource:
                unit.return_resource()
                queue = True

            if not unit(plan.ability["ability"], target=plan.target, queue=queue, subtract_cost=True):
                if self.debug:
                    print("objective failed:" + str(plan))
                    raise Exception()

            if plan.item == UnitTypeId.LAIR:
                took_action = True

            took_action = True

            # if self.is_structure(plan.item):
            #     pass
            # else:
            #     self.observation.remove_plan(plan)
            #     self.observation.add_pending(plan.item, unit)

            #     i -= 1
            #     self.macro_plans.pop(i)


    def get_owned_geysers(self):
        for base in self.bases:
            if not base.townhall:
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

    def positions_in_range(self, unit: Unit) -> Iterable[Point2]:

        unit_range = unit.radius + self.get_unit_range(unit)

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

    async def micro(self):

        friends = list(self.enumerate_army())

        enemies = list(self.all_enemy_units)
        if self.destroy_destructables():
            enemies.extend(self.destructables_fixed)

        friends.sort(key=lambda u:u.tag)
        enemies.sort(key=lambda u:u.tag)

        blur_sigma = 9
        enemy_map_blur = ndimage.gaussian_filter(self.enemy_map, blur_sigma)
        friend_map_blur = ndimage.gaussian_filter(self.friend_map, blur_sigma)

        # unblurred = np.sum(self.enemy_map * (1 - self.distance_map) * np.transpose(self.game_info.pathing_grid.data_numpy))
        # blurred = np.sum(enemy_map_blur * (1 - self.distance_map) * np.transpose(self.game_info.pathing_grid.data_numpy))
        # print(unblurred / max(1, blurred))

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

        self.enemy_gradient_map = np.stack(np.gradient(enemy_map_blur), axis=2)
            
        for unit in friends:

            UnitSingle(unit.tag).micro(
                self,
                enemies,
                friend_map_blur,
                enemy_map_blur,
                self.enemy_gradient_map,
                dodge_elements
            )

    async def get_target_position(self, target: UnitTypeId, trainer: Unit) -> Point2:
        if target in STATIC_DEFENSE[self.race]:
            townhalls = self.townhalls.ready.sorted_by_distance_to(self.start_location)
            if townhalls.exists:
                i = (self.count(target) - 1) % townhalls.amount
                return townhalls[i].position.towards(self.game_info.map_center, -5)
            else:
                return self.start_location
        elif self.is_structure(target):
            if target in race_townhalls[self.race]:
                for b in self.bases:
                    if b.townhall:
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

    def assess_threat_level(self):

        self.enemy_map = np.zeros(self.game_info.map_size)
        for enemy in self.enemies.values():
            self.enemy_map[enemy.position.rounded] += unitValue(enemy)

        self.friend_map = np.zeros(self.game_info.map_size)
        for friend in self.enumerate_army():
            self.friend_map[friend.position.rounded] += unitValue(friend)
 
        value_self = np.sum(self.friend_map)
        value_enemy = np.sum(self.enemy_map * (1 - self.distance_map) * np.transpose(self.game_info.pathing_grid.data_numpy))
        self.threat_level = value_enemy / max(1, value_self + value_enemy)


    def pull_workers(self):

        self.drafted_civilians = {
            u for u in self.drafted_civilians
            if u in self.unit_by_tag
        }
        
        if 0.6 < self.threat_level and self.time < 4 * 60:
            # if not self.count(UnitTypeId.SPINECRAWLER):
            #     plan = MacroPlan(UnitTypeId.SPINECRAWLER)
            #     plan.target = self.bases[0].mineral_patches.position
            #     self.add_macro_plan(plan)
            worker = self.bases.try_remove_any()
            if worker:
                self.drafted_civilians.add(worker)
        elif self.threat_level < 0.5:
            if any(self.drafted_civilians):
                worker = self.drafted_civilians.pop()
                if not self.bases.try_add(worker):
                    raise Exception

    def enumerate_army(self):
        for unit in self.units:
            if not unit.type_id in CIVILIANS:
                yield unit
            elif unit.tag in self.drafted_civilians:
                yield unit
            else:
                pass

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