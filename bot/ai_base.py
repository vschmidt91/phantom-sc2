import cProfile
import logging
import math
import os
import pstats
import random
from functools import cmp_to_key, lru_cache
from itertools import chain
from typing import Iterable, Type

import numpy as np
from ares import AresBot
from ares.cache import property_cache_once_per_frame
from sc2.constants import IS_DETECTOR
from sc2.data import ActionResult, Race, Result, race_townhalls
from sc2.game_state import ActionRawUnitCommand
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2, Point3
from sc2.unit import Unit, UnitCommand, UnitOrder
from sc2.units import Units
from scipy.ndimage import gaussian_filter
from skimage.draw import rectangle

from bot.behaviors.overlord_drop import OverlordDropManager

from .behaviors.inject import InjectManager
from .constants import (
    GAS_BY_RACE,
    LARVA_COST,
    RANGE_UPGRADES,
    REQUIREMENTS_KEYS,
    RESEARCH_INFO,
    TRAIN_INFO,
    UNIT_TRAINED_FROM,
    UPGRADE_RESEARCHED_FROM,
    VERSION_FILE,
    WITH_TECH_EQUIVALENTS,
    WORKERS,
    ZERG_ARMOR_UPGRADES,
    ZERG_FLYER_ARMOR_UPGRADES,
    ZERG_FLYER_UPGRADES,
    ZERG_MELEE_UPGRADES,
    ZERG_RANGED_UPGRADES, CIVILIANS,
)
from .cost import Cost
from .modules.chat import Chat
from .modules.combat import CombatModule
from .modules.dodge import DodgeModule, DodgeElement, DodgeEffect
from .modules.macro import MacroBehavior, MacroId, MacroModule, compare_plans
from .modules.scout import ScoutModule
from .modules.unit_manager import UnitManager
from .resources.base import Base
from .resources.mineral_patch import MineralPatch
from .resources.resource_manager import ResourceManager
from .resources.vespene_geyser import VespeneGeyser
from .strategies.hatch_first import HatchFirst
from .strategies.strategy import Strategy
from .units.unit import AIUnit
from .units.worker import Worker
from .utils import flood_fill


def order_matches_command(order: UnitOrder, command: UnitCommand) -> bool:
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


class AIBase(AresBot):
    def __init__(
        self,
    ):
        self.raw_affects_selection = True
        self.game_step: int = 2
        self.unit_command_uses_self_do = True

        self.strategy_cls: Type[Strategy] = HatchFirst

        if os.path.exists(VERSION_FILE):
            with open(VERSION_FILE) as f:
                self.version = f.read()

        self.debug: bool = False

        self.extractor_trick_enabled: bool = False
        self.iteration: int = 0
        self.profiler: cProfile.Profile | None = None

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
        await super().on_before_start()

        self.unit_cost = {type_id: self.get_cost(type_id) for type_id in UnitTypeId}

        if self.debug:
            logging.basicConfig(level=logging.DEBUG)
        else:
            logging.basicConfig(level=logging.ERROR)

        self.client.game_step = self.game_step

    def upgrades_by_unit(self, unit: UnitTypeId) -> Iterable[UpgradeId]:
        if unit == UnitTypeId.ZERGLING:
            return chain(
                (UpgradeId.ZERGLINGMOVEMENTSPEED,),
                # (UpgradeId.ZERGLINGMOVEMENTSPEED, UpgradeId.ZERGLINGATTACKSPEED),
                # self.upgrade_sequence(ZERG_MELEE_UPGRADES),
                # self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.ULTRALISK:
            return chain(
                (UpgradeId.CHITINOUSPLATING, UpgradeId.ANABOLICSYNTHESIS),
                self.upgrade_sequence(ZERG_MELEE_UPGRADES),
                self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.BANELING:
            return chain(
                (UpgradeId.CENTRIFICALHOOKS,),
                self.upgrade_sequence(ZERG_MELEE_UPGRADES),
                self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.ROACH:
            return chain(
                (UpgradeId.GLIALRECONSTITUTION, UpgradeId.BURROW, UpgradeId.TUNNELINGCLAWS),
                # (UpgradeId.GLIALRECONSTITUTION,),
                self.upgrade_sequence(ZERG_RANGED_UPGRADES),
                self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.HYDRALISK:
            return chain(
                (UpgradeId.EVOLVEGROOVEDSPINES, UpgradeId.EVOLVEMUSCULARAUGMENTS),
                self.upgrade_sequence(ZERG_RANGED_UPGRADES),
                self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.QUEEN:
            return chain(
                # self.upgradeSequence(ZERG_RANGED_UPGRADES),
                # self.upgradeSequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.MUTALISK:
            return chain(
                self.upgrade_sequence(ZERG_FLYER_UPGRADES),
                self.upgrade_sequence(ZERG_FLYER_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.CORRUPTOR:
            return chain(
                self.upgrade_sequence(ZERG_FLYER_UPGRADES),
                self.upgrade_sequence(ZERG_FLYER_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.BROODLORD:
            return chain(
                self.upgrade_sequence(ZERG_FLYER_ARMOR_UPGRADES),
                self.upgrade_sequence(ZERG_MELEE_UPGRADES),
                self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.OVERSEER:
            return (UpgradeId.OVERLORDSPEED,)
        else:
            return []

    async def on_start(self):
        await super().on_start()

        # await self.client.debug_create_unit([[UnitTypeId.ROACHBURROWED, 40, self.game_info.map_center, 2]])
        # await self.client.debug_create_unit([[UnitTypeId.ROACHBURROWED, 30, self.game_info.map_center, 1]])
        # await self.client.debug_upgrade()

        # await self.client.debug_create_unit([
        #     [UnitTypeId.OVERLORDTRANSPORT, 1, self.game_info.map_center, 1],
        #     [UnitTypeId.ZERGLING, 8, self.game_info.map_center, 1],
        # ])

        # await self.client.debug_create_unit([
        #     [UnitTypeId.QUEEN, 3, self.start_location, 1],
        # ])

        for townhall in self.townhalls:
            self.do(townhall(AbilityId.RALLY_WORKERS, target=townhall))

        pathing_grid = self.game_info.pathing_grid.data_numpy.transpose()
        border_x, border_y = np.gradient(pathing_grid)
        self.pathing_border = np.stack(
            [
                border_x,
                border_y,
            ],
            axis=-1,
        )

        self.distance_ground, self.distance_air = self.create_distance_map()
        self.enemy_main = self.create_enemy_main_map()

        bases = await self.initialize_bases()
        self.resource_manager = ResourceManager(self, bases)
        self.scout = ScoutModule(self)
        self.unit_manager = UnitManager(self)
        self.macro = MacroModule(self)
        self.chat = Chat(self)
        self.combat = CombatModule(self)
        self.dodge = DodgeModule(self)
        self.inject = InjectManager(self)
        self.drops = OverlordDropManager(self)
        self.strategy: Strategy = self.strategy_cls(self)

        for step in self.strategy.build_order():
            plan = self.macro.add_plan(step)
            plan.priority = math.inf

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

    def units_detecting(self, unit: Unit) -> Iterable[AIUnit]:
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
        elif behavior.unit.type_id in {
            UnitTypeId.DRONE,
            UnitTypeId.SCV,
            UnitTypeId.PROBE,
        }:
            return
        elif behavior.unit.type_id in {UnitTypeId.LARVA, UnitTypeId.EGG}:
            candidates = list(
                chain(
                    self.unit_manager.actual_by_type[UnitTypeId.LARVA], self.unit_manager.actual_by_type[UnitTypeId.EGG]
                )
            )
        else:
            candidates = [behavior]
        actual_behavior = next(
            (b for b in candidates if (isinstance(b, MacroBehavior) and b.plan and b.macro_ability == action.exact_id)),
            None,
        )

        if actual_behavior:
            # if behavior.unit and actual_behavior.unit:
            #     d = behavior.unit.position.distance_to(actual_behavior.unit.position)
            #     if 1 < d:
            #         print(d)
            actual_behavior.plan = None
        # else:
        #     logging.error(f'trainer not found: {action}')

    async def kill_random_units(self, chance: float = 3e-4) -> None:
        tags = [unit.tag for unit in self.all_own_units if random.random() < chance]
        if tags:
            await self.client.debug_kill_unit(tags)

    @lru_cache(maxsize=None)
    def get_cost(self, item: MacroId) -> Cost:
        try:
            minerals_vespene = self.calculate_cost(item)
            food = self.calculate_supply_cost(item)
        except Exception:
            return Cost(0.0, 0.0, 0.0, 0.0)
        larva = LARVA_COST.get(item, 0.0)
        return Cost(float(minerals_vespene.minerals), float(minerals_vespene.vespene), food, larva)

    async def on_step(self, iteration: int):
        await super().on_step(iteration)

        if iteration == 0 and self.debug:
            return

        self.iteration = iteration

        if 1 < self.time:
            await self.chat.add_message("(glhf)")

        if self.profiler:
            self.profiler.enable()

        if self.extractor_trick_enabled and self.supply_left <= 0:
            for gas in self.gas_buildings.not_ready:
                self.do(gas(AbilityId.CANCEL))
                self.extractor_trick_enabled = False
                break

        self.handle_errors()
        self.handle_actions()

        self.creep_placement_map = (
            (self.state.creep.data_numpy == 1)
            & (self.state.visibility.data_numpy == 2)
            & (self.game_info.pathing_grid.data_numpy == 1)
        ).transpose()
        self.creep_value_map = (
            ((self.state.creep.data_numpy == 0) & (self.game_info.pathing_grid.data_numpy == 1))
            .transpose()
            .astype(float)
        )

        def convert_rect_coords(coords: np.ndarray):
            return coords[0].astype(int).flatten(), coords[1].astype(int).flatten()

        base_size = Point2((5, 5))
        static_defense_size = Point2((2, 2))
        for base in self.resource_manager.bases:
            # d = disk(base, 4, shape=self.game_info.map_size)
            # self.creep_placement_map[d] = False
            # self.creep_value_map[d] *= 3

            r = convert_rect_coords(
                rectangle(base.position - 0.5 * base_size, extent=base_size, shape=self.game_info.map_size)
            )
            self.creep_placement_map[r] = False
            self.creep_value_map[r] *= 3

            r = convert_rect_coords(
                rectangle(
                    base.static_defense_position - 0.5 * static_defense_size,
                    extent=static_defense_size,
                    shape=self.game_info.map_size,
                )
            )
            self.creep_placement_map[r] = False

        self.creep_value_map_blurred = gaussian_filter(self.creep_value_map, 3)

        modules = [
            self.unit_manager,
            self.strategy,
            self.macro,
            self.resource_manager,
            self.scout,
            self.dodge,
            self.combat,
            self.chat,
            self.inject,
            self.drops,
        ]
        for module in modules:
            await module.on_step()

        if self.profiler:
            self.profiler.disable()
            stats = pstats.Stats(self.profiler)
            if iteration % 100 == 0:
                logging.info("dump profiling")
                stats = stats.strip_dirs().sort_stats(pstats.SortKey.CUMULATIVE)
                stats.dump_stats(filename="profiling.prof")

        if self.debug:
            await self.draw_debug()

        # if iteration % 100 == 0:
        #     self.distance_ground, self.distance_air = self.create_distance_map()

        if self.debug:
            # if 90 < self.time:
            #     await self.kill_random_units()
            worker_count = sum(1 for b in self.unit_manager.units.values() if isinstance(b, Worker))
            if worker_count != self.supply_workers:
                logging.error("worker supply mismatch")

    async def on_end(self, game_result: Result):
        await super().on_end(game_result)

    async def on_building_construction_started(self, unit: Unit):
        await super().on_building_construction_started(unit)

        behavior = self.unit_manager.add_unit(unit)
        # self.unit_manager.pending_by_type[unit.type_id].append(behavior)

        if self.race == Race.Zerg:
            if unit.type_id in {UnitTypeId.CREEPTUMOR, UnitTypeId.CREEPTUMORQUEEN, UnitTypeId.CREEPTUMORBURROWED}:
                # print('tumor')
                pass
            else:
                geyser = self.resource_manager.resource_by_position.get(unit.position)
                geyser_tag = geyser.unit.tag if isinstance(geyser, VespeneGeyser) and geyser.unit else None
                for trainer_type in UNIT_TRAINED_FROM.get(unit.type_id, []):
                    for trainer in self.unit_manager.actual_by_type[trainer_type]:
                        if trainer.unit.position.distance_to(unit.position) < 0.5:
                            if behavior := self.unit_manager.units.get(trainer.unit.tag):
                                if isinstance(behavior, MacroBehavior):
                                    behavior.plan = None
                            assert self.unit_manager.try_remove_unit(trainer.unit.tag)
                            break
                        elif not trainer.unit.is_idle and trainer.unit.order_target in {unit.position, geyser_tag}:
                            assert self.unit_manager.try_remove_unit(trainer.unit.tag)
                            break
                    else:
                        logging.error("trainer not found")

    async def on_building_construction_complete(self, unit: Unit):
        await super().on_building_construction_complete(unit)

    async def on_enemy_unit_entered_vision(self, unit: Unit):
        await super().on_enemy_unit_entered_vision(unit)

    async def on_enemy_unit_left_vision(self, unit_tag: int):
        await super().on_enemy_unit_left_vision(unit_tag)

    async def on_unit_destroyed(self, unit_tag: int):
        await super().on_unit_destroyed(unit_tag)
        self.unit_manager.try_remove_unit(unit_tag)

    async def on_unit_created(self, unit: Unit):
        await super().on_unit_created(unit)
        self.unit_manager.add_unit(unit)

    async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId):
        await super().on_unit_type_changed(unit, previous_type)

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float):
        await super().on_unit_took_damage(unit, amount_damage_taken)

    async def on_upgrade_complete(self, upgrade: UpgradeId):
        await super().on_upgrade_complete(upgrade)

    def count(
        self, item: MacroId, include_pending: bool = True, include_planned: bool = True, include_actual: bool = True
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
        start_bases = {self.start_location, *self.enemy_start_locations}

        bases = []
        for position, resources in self.expansion_locations_dict.items():
            if position not in start_bases and not await self.can_place_single(UnitTypeId.HATCHERY, position):
                continue
            base = Base(
                position,
                (MineralPatch(m) for m in resources.mineral_field),
                (VespeneGeyser(g) for g in resources.vespene_geyser),
            )
            bases.append(base)

        bases = sorted(
            bases,
            key=lambda b: self.distance_ground[b.position.rounded] + self.distance_air[b.position.rounded],
        )

        return bases

    def enumerate_positions(self, structure: Unit) -> Iterable[Point2]:
        radius = structure.footprint_radius
        return (
            structure.position + Point2((x_offset, y_offset))
            for x_offset in np.arange(-radius, +radius + 1)
            for y_offset in np.arange(-radius, +radius + 1)
        )

    def create_enemy_main_map(self) -> np.ndarray:
        weight = np.where(
            np.transpose(self.game_info.placement_grid.data_numpy) == 1,
            1.0,
            np.inf,
        )
        origins = [p.rounded for p in self.enemy_start_locations]
        enemy_main = flood_fill(
            weight,
            origins,
        )
        enemy_main = np.isfinite(enemy_main)
        return enemy_main

    def create_distance_map(self) -> tuple[np.ndarray, np.ndarray]:
        pathing = np.transpose(self.game_info.pathing_grid.data_numpy)
        for townhall in self.townhalls:
            for position in self.enumerate_positions(townhall):
                pathing[position.rounded] = 1

        weight_ground = np.where(
            np.transpose(self.game_info.pathing_grid.data_numpy) == 0,
            np.inf,
            1.0,
        )
        origins = [th.position.rounded for th in self.townhalls]
        distance_ground = flood_fill(
            weight_ground,
            origins,
        )
        distance_ground = np.where(np.isinf(distance_ground), np.nan, distance_ground)
        distance_ground /= np.nanmax(distance_ground)
        distance_ground = np.where(np.isnan(distance_ground), 1, distance_ground)

        weight_air = np.where(
            np.transpose(self.game_info.pathing_grid.data_numpy) == 0,
            1.0,
            10.0,
        )
        weight_air[0 : self.game_info.playable_area.x, :] = np.inf
        weight_air[self.game_info.playable_area.right : -1, :] = np.inf
        weight_air[:, 0 : self.game_info.playable_area.y] = np.inf
        weight_air[:, self.game_info.playable_area.top : -1] = np.inf
        distance_air = flood_fill(
            weight_air,
            origins,
        )
        distance_air = np.where(np.isinf(distance_air), np.nan, distance_air)
        distance_air /= np.nanmax(distance_air)
        distance_air = np.where(np.isnan(distance_air), 1, distance_air)

        return distance_ground, distance_air

    async def draw_debug(self):
        font_color = (255, 255, 255)
        font_size = 12

        plans = []
        plans.extend(b.plan for b in self.unit_manager.units.values() if isinstance(b, MacroBehavior) and b.plan)
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
                (
                    tag
                    for tag, behavior in self.unit_manager.units.items()
                    if isinstance(behavior, MacroBehavior) and behavior.plan == target
                ),
                None,
            )
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

        for enemy in self.all_enemy_units:
            pos = enemy.position
            position = Point3((*pos, self.get_terrain_z_height(pos)))
            text = f"{enemy.name}"
            self.client.debug_text_world(text, position, color=font_color, size=font_size)

        self.client.debug_text_screen(f"Confidence: {round(100 * self.combat.confidence)}%", (0.01, 0.01))
        self.client.debug_text_screen(f"Gas Target: {round(self.resource_manager.get_gas_target(), 3)}", (0.01, 0.03))

        for i, plan in enumerate(plans):
            self.client.debug_text_screen(f"{1 + i} {round(plan.eta or 0, 1)} {plan.item.name}", (0.01, 0.1 + 0.01 * i))

        # self.figure_img.set_data(self.combat.army_map.data[:, :, [0, 1, 4]])
        # self.figure.canvas.draw()
        # self.figure.canvas.flush_events()

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
            self.count(e, include_pending=False, include_planned=False) == 0 for e in WITH_TECH_EQUIVALENTS[unit]
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
        if (required_building := info.get("required_building")) and self.is_unit_missing(required_building):
            yield required_building
        if (required_upgrade := info.get("required_upgrade")) and self.is_upgrade_missing(required_upgrade):
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

    def get_unit_value(self, unit: Unit) -> float:
        health = unit.health + unit.shield
        dps = max(unit.ground_dps, unit.air_dps)
        return math.sqrt(health * dps)

    def get_unit_cost(self, unit_type: UnitTypeId) -> int:
        cost = self.calculate_unit_value(unit_type)
        return cost.minerals + cost.vespene

    def get_max_harvester(self) -> int:
        workers = sum(b.harvester_target for b in self.resource_manager.bases_taken)
        workers += 16 * self.count(UnitTypeId.HATCHERY, include_actual=False, include_planned=False)
        workers += 3 * self.count(GAS_BY_RACE[self.race], include_actual=False, include_planned=False)
        return workers

    @property
    def army(self) -> Units:
        return self.all_own_units.exclude_type(CIVILIANS)

    @property
    def enemy_army(self) -> Units:
        return self.all_enemy_units.exclude_type(CIVILIANS)

    @property
    def civilians(self) -> Units:
        return self.all_own_units(CIVILIANS)

    @property
    def enemy_civilians(self) -> Units:
        return self.all_enemy_units(CIVILIANS)
