import cProfile
import pstats
from functools import cmp_to_key
from itertools import chain
import logging
from dataclasses import dataclass
import os
import math
from random import random
from typing import Optional, Type, Dict, Iterable
import numpy as np

from sc2.bot_ai import BotAI
from sc2.constants import IS_DETECTOR
from sc2.data import Result, race_townhalls, ActionResult, Race
from sc2.game_state import ActionRawUnitCommand
from sc2.position import Point2, Point3
from sc2.unit import Unit, UnitOrder, UnitCommand
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.ids.upgrade_id import UpgradeId

from MapAnalyzer import MapData

from .utils import flood_fill
from .constants import WORKERS, UNIT_TRAINED_FROM, WITH_TECH_EQUIVALENTS
from .constants import GAS_BY_RACE, REQUIREMENTS_KEYS
from .constants import TRAIN_INFO, UPGRADE_RESEARCHED_FROM, RESEARCH_INFO, RANGE_UPGRADES
from .resources.resource_manager import ResourceManager
from .strategies.hatch_first import HatchFirst
from .techtree import TechTree
from .behaviors.inject import InjectManager
from .behaviors.survive import SurviveBehavior
from .units.unit import CommandableUnit
from .modules.chat import Chat
from .modules.combat import CombatModule
from .modules.dodge import DodgeModule
from .modules.macro import MacroBehavior, MacroId, MacroModule, compare_plans
from .modules.scout import ScoutModule
from .modules.unit_manager import IGNORED_UNIT_TYPES, UnitManager
from .resources.base import Base
from .resources.mineral_patch import MineralPatch
from .resources.vespene_geyser import VespeneGeyser
from .strategies.strategy import Strategy
from .units.worker import Worker, WorkerManager

class AIBase(BotAI):

    def __init__(self,
        strategy_cls: Optional[Type[Strategy]] = None,
        version_path = "version.txt"
    ):

        self.raw_affects_selection = True
        self.game_step: int = 2

        self.strategy_cls: Type[Strategy] = strategy_cls or HatchFirst
        with open(version_path, 'r', encoding="UTF-8") as file:
            self.version = file.readline().replace('\n', '')
        self.debug: bool = False
        self.destroy_destructables: bool = False
        self.unit_command_uses_self_do = True

        self.enemies: Dict[int, Unit] = dict()

        self.extractor_trick_enabled: bool = False
        self.iteration: int = 0
        self.techtree: TechTree = TechTree('data/techtree.json')
        self.profiler: Optional[cProfile.Profile] = None

        super().__init__()

    def can_move(self, unit: Unit) -> bool:
        if unit.is_burrowed:
            if unit.type_id == UnitTypeId.INFESTORBURROWED:
                return True
            elif unit.type_id == UnitTypeId.ROACHBURROWED:
                return UpgradeId.TUNNELINGCLAWS in self.state.upgrades
            return False
        return 0 < unit.movement_speed

    async def on_before_start(self):

        if self.debug:
            logging.basicConfig(level=logging.DEBUG)
            self.profiler = cProfile.Profile()
            # plt.ion()
            # self.plot, self.plot_axes = plt.subplots(1, 2)
            # self.plot_images = None
        else:
            logging.basicConfig(level=logging.ERROR)

        logging.debug('before_start')

        self.client.game_step = self.game_step

    async def on_start(self):

        logging.debug('start')

        for townhall in self.townhalls:
            self.do(townhall(AbilityId.RALLY_WORKERS, target=townhall))

        self.map_analyzer = MapData(self)
        self.distance_map = self.create_distance_map()
        bases = await self.initialize_bases()
        self.resource_manager = ResourceManager(self, bases)
        self.scout = ScoutModule(self)
        self.unit_manager = UnitManager(self)
        self.macro = MacroModule(self)
        self.chat = Chat(self)
        self.combat = CombatModule(self)
        self.dodge = DodgeModule(self)
        self.inject = InjectManager(self)
        self.strategy: Strategy = self.strategy_cls(self)
        self.worker_manager: WorkerManager = WorkerManager(self)

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
                logging.error("creep tumor not found")

        behavior = self.unit_manager.units.get(tag)
        if not behavior:
            return
        elif not behavior.unit:
            return
        elif behavior.unit.type_id == UnitTypeId.DRONE:
            return
        elif behavior.unit.type_id in {UnitTypeId.LARVA, UnitTypeId.EGG}:
            candidates = list(chain(self.unit_manager.actual_by_type[UnitTypeId.LARVA],
                               self.unit_manager.actual_by_type[UnitTypeId.EGG]))
        else:
            candidates = [behavior]
        actual_behavior = next((
            b
            for b in candidates
            if (
                isinstance(b, MacroBehavior)
                and b.plan
                and b.macro_ability == action.exact_id
            )
        ),
            None)
        if actual_behavior:
            actual_behavior.plan = None
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

        modules = [
            self.unit_manager,
            self.resource_manager,
            self.scout,
            self.macro,
            self.dodge,
            self.combat,
            self.chat,
            self.inject,
            self.strategy,
            self.worker_manager
        ]
        for module in modules:
            await module.on_step()

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
        logging.debug("end: %s", game_result)

    async def on_building_construction_started(self, unit: Unit):
        logging.debug("building_construction_started: %s", unit)

        behavior = self.unit_manager.add_unit(unit)
        # self.unit_manager.pending_by_type[unit.type_id].append(behavior)

        if self.race == Race.Zerg:
            if unit.type_id in {
                UnitTypeId.CREEPTUMOR,
                UnitTypeId.CREEPTUMORQUEEN,
                UnitTypeId.CREEPTUMORBURROWED
            }:
                # print('tumor')
                pass
            else:
                geyser = self.resource_manager.resource_by_position.get(unit.position)
                geyser_tag = geyser.unit.tag if isinstance(geyser, VespeneGeyser) and geyser.unit else None
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
                        ):
                            assert self.unit_manager.try_remove_unit(trainer.unit.tag)
                            break
                    else:
                        logging.error('trainer not found')

    async def on_building_construction_complete(self, unit: Unit):
        logging.debug("building_construction_complete: %s", unit)

    async def on_enemy_unit_entered_vision(self, unit: Unit):
        logging.debug("enemy_unit_entered_vision: %s", unit)
        if unit.is_snapshot:
            return
        if unit.tag not in self.unit_manager.enemies:
            self.unit_manager.add_unit(unit)

    async def on_enemy_unit_left_vision(self, unit_tag: int):
        logging.debug("enemy_unit_left_vision: %i", unit_tag)

    async def on_unit_destroyed(self, unit_tag: int):
        logging.debug("unit_destroyed: %i", unit_tag)
        self.unit_manager.enemies.pop(unit_tag, None)
        self.unit_manager.try_remove_unit(unit_tag)

    async def on_unit_created(self, unit: Unit):
        logging.debug("unit_created: %s", unit)
        self.unit_manager.add_unit(unit)

    async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId):
        logging.debug("unit_type_changed: %s -> %s", previous_type, unit)

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float):
        logging.debug("unit_took_damage: %f @ %s", amount_damage_taken, unit)

    async def on_upgrade_complete(self, upgrade: UpgradeId):
        logging.info("upgrade_complete: %s", upgrade)

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
        for expansion in self.expansion_locations_list:
            if expansion in exclude_bases:
                continue
            if await self.can_place_single(UnitTypeId.HATCHERY, expansion):
                continue
            positions_fixed[expansion] = await self.find_placement(
                UnitTypeId.HATCHERY,
                expansion,
                placement_step=1
            )

        bases = sorted(
            (
                Base(
                    self,
                    positions_fixed.get(position, position),
                    (MineralPatch(self, m) for m in resources.mineral_field),
                    (VespeneGeyser(self, g) for g in resources.vespene_geyser)
                )
            for position, resources in self.expansion_locations_dict.items()
        ),
        key=lambda b: self.distance_map[b.position.rounded] - .5 * b.position.distance_to(self.enemy_start_locations[0]) / self.game_info.map_size.length)

        return bases

    def enumerate_positions(self, structure: Unit) -> Iterable[Point2]:
        radius = structure.footprint_radius
        return (
            structure.position + Point2((x_offset, y_offset))
            for x_offset in np.arange(-radius, +radius + 1)
            for y_offset in np.arange(-radius, +radius + 1)
        )

    def create_distance_map(self) -> np.ndarray:

        boundary = np.transpose(self.game_info.pathing_grid.data_numpy == 0)
        for townhall in self.townhalls:
            for position in self.enumerate_positions(townhall):
                boundary[position.rounded] = False

        distance_ground_self = flood_fill(
            boundary,
            [self.start_location.rounded]
        )
        distance_ground_enemy = flood_fill(
            boundary,
            [p.rounded for p in self.enemy_start_locations]
        )
        distance_ground = distance_ground_self / (distance_ground_self + distance_ground_enemy)
        distance_air = np.zeros_like(distance_ground)
        for position, _ in np.ndenumerate(distance_ground):
            position = Point2(position)
            distance_self = position.distance_to(self.start_location)
            distance_enemy = min(position.distance_to(p) for p in self.enemy_start_locations)
            distance_air[position] = distance_self / (distance_self + distance_enemy)
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
        plans.sort(key=cmp_to_key(compare_plans), reverse=True)

        for i, target in enumerate(plans):

            positions = []

            if not target.target:
                pass
            elif isinstance(target.target, Unit):
                positions.append(target.target.position3d)
            elif isinstance(target.target, Point3):
                positions.append(target.target)
            elif isinstance(target.target, Point2):
                height = self.get_terrain_z_height(target.target)
                positions.append(Point3((target.target.x, target.target.y, height)))

            unit_tag = next(
                (tag
                 for tag, behavior in self.unit_manager.units.items()
                 if isinstance(behavior, MacroBehavior) and behavior.plan == target), None)
            if (behavior := self.unit_manager.units.get(unit_tag)) and behavior.unit:
                positions.append(behavior.unit.position3d)

            text = f"{str(i + 1)} {target.item.name}"

            for position in positions:
                self.client.debug_text_world(text, position, color=font_color, size=font_size)

            if len(positions) == 2:
                position_from, position_to = positions
                position_from += Point3((0.0, 0.0, 0.1))
                position_to += Point3((0.0, 0.0, 0.1))
                self.client.debug_line_out(position_from, position_to, color=font_color)

        font_color = (255, 0, 0)

        for enemy in self.unit_manager.enemies.values():

            if enemy.unit:
                pos = enemy.unit.position
                position = Point3((*pos, self.get_terrain_z_height(pos)))
                text = f"{enemy.unit.name}"
                self.client.debug_text_world(text, position, color=font_color, size=font_size)

        self.client.debug_text_screen(
            f'Threat Level: {round(100 * self.combat.threat_level)}%',
            (0.01, 0.01)
        )
        self.client.debug_text_screen(
            f'Gas Target: {round(self.resource_manager.get_gas_target(), 3)}',
            (0.01, 0.03)
        )

        for i, plan in enumerate(plans):
            self.client.debug_text_screen(
                f'{1 + i} {round(plan.eta or 0, 1)} {plan.item.name}',
                (0.01, 0.1 + 0.01 * i)
            )

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

        if isinstance(item, UnitTypeId):
            trainers = UNIT_TRAINED_FROM[item]
            trainer = min(trainers, key=lambda v: v.value)
            info = TRAIN_INFO[trainer][item]
        elif isinstance(item, UpgradeId):
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
        unit_range = 0.0
        if ground:
            unit_range = max(unit_range, unit.ground_range)
        if air:
            unit_range = max(unit_range, unit.air_range)

        if unit.is_mine and (boni := RANGE_UPGRADES.get(unit.type_id)):
            for upgrade, bonus in boni.items():
                if upgrade in self.state.upgrades:
                    unit_range += bonus

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
        dps = max(unit.ground_dps, unit.air_dps)
        return math.sqrt(health * dps)

    def get_unit_cost(self, unit_type: UnitTypeId) -> int:
        cost = self.calculate_unit_value(unit_type)
        return cost.minerals + cost.vespene

    def get_max_harvester(self) -> int:
        workers = 0
        workers += sum((b.harvester_target for b in self.resource_manager.bases_taken))
        workers += 16 * self.count(UnitTypeId.HATCHERY, include_actual=False, include_planned=False)
        workers += 3 * self.count(
            GAS_BY_RACE[self.race],
            include_actual=False,
            include_planned=False
        )
        return workers

    def blocked_bases(self, position: Point2, margin: float = 0.0) -> Iterable[Base]:
        townhall_type = next(iter(race_townhalls[self.race]))
        radius = self.techtree.units[townhall_type].radius or 0.0
        return (
            base
            for base in self.resource_manager.bases
            if np.linalg.norm(position - base.position, ord=1) < margin + radius
        )
