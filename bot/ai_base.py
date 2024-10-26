import cProfile
import logging
import math
import os
import pstats
from collections import defaultdict
from functools import cmp_to_key
from typing import Iterable

import numpy as np
from ares import AresBot
from loguru import logger
from sc2.constants import IS_DETECTOR
from sc2.data import ActionResult, Race, Result, race_townhalls
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2, Point3
from sc2.unit import Unit

from .action import Action
from .components.build_order import BuildOrder
from .components.combat import CombatModule
from .components.creep import CreepSpread
from .components.dodge import DodgeModule
from .components.inject import InjectManager
from .components.macro import MacroId, MacroModule, compare_plans
from .components.scout import ScoutModule
from .components.strategy import Strategy
from .constants import (
    GAS_BY_RACE,
    REQUIREMENTS_KEYS,
    RESEARCH_INFO,
    SUPPLY_PROVIDED,
    TRAIN_INFO,
    UNIT_TRAINED_FROM,
    UPGRADE_RESEARCHED_FROM,
    VERSION_FILE,
    WITH_TECH_EQUIVALENTS,
    WORKERS,
)
from .cost import CostManager
from .modules.chat import Chat
from .modules.unit_manager import UnitManager
from .resources.resource_manager import ResourceManager


class PhantomBot(
    BuildOrder, CombatModule, CreepSpread, DodgeModule, InjectManager, MacroModule, ScoutModule, Strategy, AresBot
):
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

    async def on_before_start(self):
        await super().on_before_start()
        if self.debug:
            logging.basicConfig(level=logging.DEBUG)
        else:
            logging.basicConfig(level=logging.ERROR)

    async def on_start(self) -> None:
        await super().on_start()

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
        self.unit_manager = UnitManager(self)
        self.chat = Chat(self)

    def handle_errors(self):
        for error in self.state.action_errors:
            logger.error(error)
            if error.result == ActionResult.CantBuildLocationInvalid.value:
                if unit := self.unit_tag_dict.get(error.unit_tag):
                    self.blocked_positions[unit.position] = self.time
                if plan := self.assigned_plans.get(error.unit_tag):
                    plan.target = None

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
            self.update_composition()

        actions: list[Action] = []
        actions.extend(self.macro())
        actions.extend(self.resource_manager.on_step())
        actions.extend(self.spread_creep())
        actions.extend(self.do_injects())
        actions.extend(self.do_scouting())
        actions.extend(self.do_dodge())
        actions.extend(self.do_combat())

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

    def units_detecting(self, unit: Unit) -> Iterable[Unit]:
        for detector_type in IS_DETECTOR:
            for detector in self.unit_manager.actual_by_type[detector_type]:
                distance = detector.position.distance_to(unit.position)
                if distance <= detector.radius + detector.detect_range + unit.radius:
                    yield detector

    async def on_end(self, game_result: Result):
        await super().on_end(game_result)

    async def on_building_construction_started(self, unit: Unit):
        await super().on_building_construction_started(unit)

        # self.unit_manager.pending_by_type[unit.type_id].append(behavior)

        if self.race == Race.Zerg:
            if unit.type_id in {UnitTypeId.CREEPTUMOR, UnitTypeId.CREEPTUMORQUEEN, UnitTypeId.CREEPTUMORBURROWED}:
                # print('tumor')
                pass
            else:
                for trainer, plan in list(self.assigned_plans.items()):
                    if (
                        plan.item == unit.type_id
                        and plan.target
                        and unit.position.distance_to(plan.target.position) < 3
                    ):
                        del self.assigned_plans[trainer]
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

    async def on_unit_created(self, unit: Unit):
        await super().on_unit_created(unit)
        if unit.type_id in {UnitTypeId.DRONE, UnitTypeId.SCV, UnitTypeId.PROBE}:
            self.resource_manager.add_harvester(unit)

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
                count += self.supply_workers
            else:
                count += len(self.unit_manager.actual_by_type[item])
        if include_pending:
            count += factor * len(self.unit_manager.pending_by_type[item])
        if include_planned:
            count += factor * sum(1 for _ in self.planned_by_type(item))

        return count

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

        self.client.debug_text_screen(f"Confidence: {round(100 * self.confidence)}%", (0.01, 0.01))
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
            if not base.townhall.is_ready:
                continue
            if base.townhall.type_id not in race_townhalls[self.race]:
                continue
            for geyser in base.vespene_geysers:
                yield geyser

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
