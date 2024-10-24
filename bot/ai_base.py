import cProfile
import logging
import math
import os
import pstats
from collections import defaultdict
from functools import cmp_to_key
from itertools import islice
from typing import Iterable

import numpy as np
from sc2.game_state import ActionRawUnitCommand
from sc2.ids.buff_id import BuffId

from ares import AresBot
from loguru import logger
from sc2.constants import IS_DETECTOR
from sc2.data import ActionResult, Race, Result, race_townhalls
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2, Point3
from sc2.unit import Unit
from sc2.units import Units

from .strategies.zerg_macro import ZergMacro
from .action import Action
from .behaviors.inject import InjectManager
from .components.build_order import BuildOrder
from .components.creep import CreepSpread
from .constants import (
    CIVILIANS,
    GAS_BY_RACE,
    RANGE_UPGRADES,
    REQUIREMENTS_KEYS,
    RESEARCH_INFO,
    TRAIN_INFO,
    UNIT_TRAINED_FROM,
    UPGRADE_RESEARCHED_FROM,
    VERSION_FILE,
    WITH_TECH_EQUIVALENTS,
    WORKERS, MACRO_INFO, SUPPLY_PROVIDED, ALL_MACRO_ABILITIES,
)
from .cost import CostManager, Cost
from .modules.chat import Chat
from .modules.combat import CombatModule
from .modules.dodge import DodgeModule
from .modules.macro import MacroId, MacroModule, compare_plans
from .modules.scout import ScoutModule
from .modules.unit_manager import UnitManager
from .resources.base import Base
from .resources.mineral_patch import MineralPatch
from .resources.resource_manager import ResourceManager
from .resources.vespene_geyser import VespeneGeyser
from .strategies.strategy import Strategy
from .units.unit import AIUnit
from .units.worker import Worker
from .utils import flood_fill


class PhantomBot(BuildOrder, CreepSpread, MacroModule, AresBot):
    def __init__(
        self,
    ) -> None:

        if os.path.exists(VERSION_FILE):
            with open(VERSION_FILE) as f:
                self.version = f.read()

        self.debug: bool = False

        self.extractor_trick_enabled: bool = False
        self.iteration: int = 0
        self.profiler: cProfile.Profile | None = None
        self.cost = CostManager(self.calculate_cost, self.calculate_supply_cost)
        super().__init__(game_step_override=2)

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

        if self.debug:
            logging.basicConfig(level=logging.DEBUG)
        else:
            logging.basicConfig(level=logging.ERROR)

    async def on_start(self) -> None:
        await super().on_start()

        # await self.client.debug_create_unit([[UnitTypeId.QUEEN, 3, self.start_location, 1]])
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

        self.enemy_main = self.create_enemy_main_map()

        bases = await self.initialize_bases()
        self.resource_manager = ResourceManager(self, bases)
        self.scout = ScoutModule(self)
        self.unit_manager = UnitManager(self)
        self.chat = Chat(self)
        self.combat = CombatModule(self)
        self.dodge = DodgeModule(self)
        self.inject = InjectManager(self)
        self.strategy: Strategy = ZergMacro(self)

        for structure in self.all_own_units:
            self.unit_manager.add_unit(structure)

    def handle_errors(self):
        for error in self.state.action_errors:
            logger.error(error)
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

    async def on_step(self, iteration: int):
        await super().on_step(iteration)

        if iteration == 0 and self.debug:
            return

        self.iteration = iteration

        if 1 < self.time:
            await self.chat.add_message("(glhf)")

        if self.profiler:
            self.profiler.enable()

        self.handle_actions()
        self.handle_errors()

        self.unit_manager.update_all_units()

        build_order_completed = self.run_build_order()

        if build_order_completed:
            self.make_composition()
            self.make_tech()
            self.morph_overlords()
            self.expand()
            self.strategy.update_composition()

        actions: list[Action] = []
        actions.extend(self.resource_manager.on_step())
        actions.extend(self.inject.on_step())
        actions.extend(self.scout.on_step())
        actions.extend(self.dodge.on_step())
        actions.extend(self.combat.on_step())
        actions.extend(self.spread_creep())
        actions.extend(self.macro())

        if self.debug:
            self.check_for_duplicate_actions(actions)
        for action in actions:
            success = await action.execute(self)
            if not success:
                logging.info(f"Action failed: {action}")

        if self.profiler:
            self.profiler.disable()
            stats = pstats.Stats(self.profiler)
            if iteration % 100 == 0:
                logging.info("dump profiling")
                stats = stats.strip_dirs().sort_stats(pstats.SortKey.CUMULATIVE)
                stats.dump_stats(filename="profiling.prof")

        if self.debug:
            await self.draw_debug()

    def check_for_duplicate_actions(self, actions: list[Action]) -> None:
        actions_of_unit: defaultdict[Unit, list[Action]] = defaultdict(list)
        for action in actions:
            if hasattr(action, "unit"):
                unit = getattr(action, "unit")
                actions_of_unit[unit].append(action)
        for unit, unit_actions in actions_of_unit.items():
            # if len(unit_actions) > 1:
            #     logger.info(f"Unit {unit} received multiple commands: {actions}")
            for a in unit_actions[1:]:
                actions.remove(a)

    async def on_end(self, game_result: Result):
        await super().on_end(game_result)

    async def on_building_construction_started(self, unit: Unit):
        await super().on_building_construction_started(unit)

        self.unit_manager.add_unit(unit)
        # self.unit_manager.pending_by_type[unit.type_id].append(behavior)

        if self.race == Race.Zerg:
            if unit.type_id in {UnitTypeId.CREEPTUMOR, UnitTypeId.CREEPTUMORQUEEN, UnitTypeId.CREEPTUMORBURROWED}:
                # print('tumor')
                pass
            else:
                for trainer, plan in list(self.assigned_plans.items()):
                    if plan.item == unit.type_id and plan.target and unit.position.distance_to(plan.target.position) < 3:
                        del self.assigned_plans[trainer]
                        self.unit_manager.try_remove_unit(trainer)
                        logger.info(f"New building matched to plan: {plan=}, {unit=}, {trainer=}")
                        break
                # geyser = self.resource_manager.resource_by_position.get(unit.position)
                # geyser_tag = geyser.unit.tag if isinstance(geyser, VespeneGeyser) and geyser.unit else None
                # for trainer_type in UNIT_TRAINED_FROM.get(unit.type_id, []):
                #     for trainer in self.unit_manager.actual_by_type[trainer_type]:
                #         if trainer.unit.position.distance_to(unit.position) < 0.5:
                #             assert self.unit_manager.try_remove_unit(trainer.unit.tag)
                #             break
                #         elif not trainer.unit.is_idle and trainer.unit.order_target in {unit.position, geyser_tag}:
                #             assert self.unit_manager.try_remove_unit(trainer.unit.tag)
                #             break
                #     else:
                #         logging.error("trainer not found")

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

    def handle_actions(self):
        for action in self.state.actions_unit_commands:
            for tag in action.unit_tags:
                self.handle_action(action, tag)

    def handle_action(self, action: ActionRawUnitCommand, tag: int) -> None:
        unit = self.unit_tag_dict.get(tag)
        if unit and unit.type_id == UnitTypeId.EGG:
            # commands issued to a specific larva will be received by a random one
            # therefore, a direct lookup will usually be incorrect
            # instead, all plans are checked for a match
            tag = next((
                t
                for t, p in self.assigned_plans.items()
                if MACRO_INFO[UnitTypeId.LARVA].get(p.item, {}).get("ability") == action.exact_id
            ), None)
        if plan := self.assigned_plans.get(tag):
            if (
                unit
                and unit.type_id != UnitTypeId.EGG
                and MACRO_INFO.get(unit.type_id, {}).get(plan.item, {}).get("ability") != action.exact_id
            ):
                return
            # if (
            #     unit
            #     and unit.type_id == UnitTypeId.DRONE
            # ):
            #     self.unit_manager.try_remove_unit(tag)
            del self.assigned_plans[tag]
            logger.info(f"Action matched plan: {action=}, {tag=}, {plan=}")

        elif action.exact_id in ALL_MACRO_ABILITIES:
            logger.info(f"Action performed by non-existing unit: {action=}, {tag=}")

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
            count += factor * sum(1 for _ in self.planned_by_type(item))

        return count

    async def initialize_bases(self):

        start_bases = {self.start_location, *self.enemy_start_locations}
        distance_ground, distance_air = self.create_distance_map()

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
            key=lambda b: distance_ground[b.position.rounded] + distance_air[b.position.rounded],
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

        plans = sorted(
            self.enumerate_plans(),
            key=cmp_to_key(compare_plans),
            reverse=True,
        )

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

    def is_upgrade_missing(self, upgrade: UpgradeId) -> bool:
        return upgrade not in self.state.upgrades

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
        else:
            raise ValueError(item)

        if self.is_unit_missing(trainer):
            yield trainer
        if (required_building := info.get("required_building")) and self.is_unit_missing(required_building):
            yield required_building
        if (
            (required_upgrade := info.get("required_upgrade"))
            and isinstance(required_upgrade, UpgradeId)
            and self.is_upgrade_missing(required_upgrade)
        ):
            yield required_upgrade


    @property
    def income(self) -> Cost:

        larva_per_second = 0.0
        for hatchery in self.townhalls:
            if hatchery.is_ready:
                larva_per_second += 1 / 11
                if hatchery.has_buff(BuffId.QUEENSPAWNLARVATIMER):
                    larva_per_second += 3 / 29

        return Cost(
            self.state.score.collection_rate_minerals,
            self.state.score.collection_rate_vespene,
            0.0,
            60.0 * larva_per_second,
        )


    def morph_overlords(self) -> None:
        supply_pending = sum(
            provided
            for unit_type, provided in SUPPLY_PROVIDED[self.race].items()
            for unit in self.unit_manager.pending_by_type[unit_type]
        )
        supply_planned = sum(
            provided
            for unit_type, provided in SUPPLY_PROVIDED[self.race].items()
            for plan in self.planned_by_type(unit_type)
        )

        if 200 <= self.supply_cap + supply_pending + supply_planned:
            return

        supply_buffer = 4.0 + self.income.larva / 2.0

        if self.supply_left + supply_pending + supply_planned <= supply_buffer:
            plan = self.add_plan(UnitTypeId.OVERLORD)
            plan.priority = 1

    def expand(self) -> None:
        # if self.count(UnitTypeId.SPAWNINGPOOL, include_pending=False, include_planned=False) < 1:
        #     return

        if self.time < 50:
            return

        worker_max = self.get_max_harvester()
        saturation = self.state.score.food_used_economy / max(1, worker_max)
        saturation = max(0, min(1, saturation))
        priority = 3 * (saturation - 1)

        expand = True
        if self.townhalls.amount == 2:
            expand = 21 <= self.state.score.food_used_economy
        elif 2 < self.townhalls.amount:
            expand = 2 / 3 < saturation

        for plan in self.planned_by_type(UnitTypeId.HATCHERY):
            if plan.priority < math.inf:
                plan.priority = priority

        if expand and self.count(UnitTypeId.HATCHERY, include_actual=False) < 1:
            logging.info("%s: expanding", self.time_formatted)
            plan = self.add_plan(UnitTypeId.HATCHERY)
            plan.priority = priority
            plan.max_distance = None
