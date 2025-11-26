import cProfile
import io
import lzma
import os
import pickle
import pstats
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Set
from dataclasses import dataclass
from itertools import chain
from queue import Empty, Queue

import numpy as np
from ares import WORKER_TYPES, AresBot
from ares.behaviors.macro.mining import TOWNHALL_RADIUS
from ares.consts import ALL_STRUCTURES
from cython_extensions import cy_distance_to
from loguru import logger
from s2clientprotocol.score_pb2 import CategoryScoreDetails
from sc2.cache import property_cache_once_per_frame
from sc2.data import Race, Result
from sc2.dicts.unit_research_abilities import RESEARCH_INFO
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.game_state import ActionRawUnitCommand
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2, Point3
from sc2.unit import Unit
from sc2.unit_command import UnitCommand
from sc2.units import Units

from phantom.agent import Agent
from phantom.common.constants import (
    ALL_MACRO_ABILITIES,
    ITEM_BY_ABILITY,
    MICRO_MAP_REGEX,
    MINING_RADIUS,
    REQUIREMENTS_KEYS,
    SUPPLY_PROVIDED,
    WITH_TECH_EQUIVALENTS,
    ZERG_ARMOR_UPGRADES,
    ZERG_FLYER_ARMOR_UPGRADES,
    ZERG_FLYER_UPGRADES,
    ZERG_MELEE_UPGRADES,
    ZERG_RANGED_UPGRADES,
)
from phantom.common.cost import Cost, CostManager
from phantom.common.utils import RNG, MacroId, Point, center, get_intersections, project_point_onto_line
from phantom.config import BotConfig
from phantom.exporter import BotExporter
from phantom.macro.main import MacroPlan
from phantom.parameters import Parameters


@dataclass(frozen=True)
class OrderedStructure:
    type: UnitTypeId
    position: Point2


class PhantomBot(BotExporter, AresBot):
    def __init__(self, config: BotConfig, opponent_id: str, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self.bot_config = config
        self.opponent_id = opponent_id
        self.replay_tags = set[str]()
        self.replay_tag_queue = Queue[str]()
        self.version: str | None = None
        self.profiler = cProfile.Profile()
        self.on_before_start_was_called = False
        self.ordered_structures = dict[int, OrderedStructure]()
        self.pending = dict[int, UnitTypeId]()
        self.pending_upgrades = dict[int, UpgradeId]()
        self.units_completed_this_frame = set[int]()
        self.parameters = Parameters()
        self.cost = CostManager(self)
        self.worker_memory = dict[int, Unit]()
        self.workers_in_gas_buildings = dict[int, Unit]()
        self.actions_by_ability = defaultdict[AbilityId, list[UnitCommand]](list)
        self.ordered_structure_position_to_tag = dict[Point2, int]()

        if os.path.isfile(self.bot_config.version_path):
            logger.info(f"Reading version from {self.bot_config.version_path}")
            with open(self.bot_config.version_path) as f:
                self.version = f.read()
        else:
            logger.warning(f"Version not found: {self.bot_config.version_path}")

    def add_replay_tag(self, replay_tag: str) -> None:
        self.replay_tag_queue.put(replay_tag)

    async def on_before_start(self) -> None:
        await super().on_before_start()
        self.on_before_start_was_called = True

    async def on_start(self) -> None:
        if not self.on_before_start_was_called:
            logger.debug("on_before_start was not called, calling it now.")
            await self.on_before_start()

        logger.debug("Bot starting")
        await super().on_start()

        self.is_micro_map = re.match(MICRO_MAP_REGEX, self.game_info.map_name)
        self.worker_memory.update({u.tag: u for u in self.workers})
        self.expansion_resource_positions = dict[Point, list[Point]]()
        self.return_point = dict[Point, Point2]()
        self.spore_position = dict[Point, Point]()
        self.spine_position = dict[Point, Point]()
        self.speedmining_positions = dict[Point, Point2]()
        self.return_distances = dict[Point, float]()
        self.enemy_start_locations_rounded = [tuple(p.rounded) for p in self.enemy_start_locations]
        self.bases = list[Point]()
        self.structure_dict = dict[Point, Unit | OrderedStructure | MacroPlan]()
        self.air_grid = np.ones_like(self.mediator.get_air_grid)

        if self.is_micro_map:
            pass
        else:
            worker_radius = self.workers[0].radius
            for base_position, resources in self.expansion_locations_dict.items():
                pathing = await self.client.query_pathing(self.workers[0], base_position)
                if pathing is not None:
                    self.bases.append(tuple(base_position.rounded))
                else:
                    print("no path to base")
                mineral_center = Point2(np.mean([r.position for r in resources], axis=0))
                self.spore_position[base_position.rounded] = tuple(base_position.towards(mineral_center, 4.0).rounded)
                self.spine_position[base_position.rounded] = tuple(
                    self.mediator.find_path_next_point(
                        start=base_position,
                        target=self.enemy_start_locations[0],
                        grid=self.mediator.get_cached_ground_grid,
                        sensitivity=5,
                        sense_danger=False,
                    ).rounded
                )
                for geyser in resources.vespene_geyser:
                    target = geyser.position.towards(base_position, geyser.radius + worker_radius)
                    self.speedmining_positions[geyser.position.rounded] = target
                for patch in resources.mineral_field:
                    target = patch.position.towards(base_position, MINING_RADIUS)
                    for patch2 in resources.mineral_field:
                        if patch.position == patch2.position:
                            continue
                        position = project_point_onto_line(target, target - base_position, patch2.position)
                        distance1 = patch.position.distance_to(base_position)
                        distance2 = patch2.position.distance_to(base_position)
                        if distance1 < distance2:
                            continue
                        if patch2.position.distance_to(position) >= MINING_RADIUS:
                            continue
                        intersections = list(
                            get_intersections(patch.position, MINING_RADIUS, patch2.position, MINING_RADIUS)
                        )
                        if intersections:
                            intersection1, intersection2 = intersections
                            if intersection1.distance_to(base_position) < intersection2.distance_to(base_position):
                                target = intersection1
                            else:
                                target = intersection2
                            break
                    self.speedmining_positions[patch.position.rounded] = target

                b = tuple(base_position.rounded)
                self.expansion_resource_positions[b] = [tuple(r.position.rounded) for r in resources]
                for r in resources:
                    p = tuple(r.position.rounded)
                    ps = self.speedmining_positions[p]
                    return_point = base_position.towards(ps, 3.125)
                    self.return_point[p] = return_point
                    self.return_distances[p] = ps.distance_to(return_point)

        self.in_mineral_line = {b: tuple(center(self.expansion_resource_positions[b]).rounded) for b in self.bases}
        self.agent = Agent(self, self.bot_config.build_order, self.parameters)

        self.send_overlord_scout()

        # await self.client.debug_create_unit(
        #     [
        #         [UnitTypeId.ROACH, 13, self.game_info.map_center, 1],
        #         [UnitTypeId.ROACH, 13, self.game_info.map_center, 2],
        #     ]
        # )

        try:
            with lzma.open(self.bot_config.params_path, "rb") as f:
                parameters = pickle.load(f)
                self.parameters.strategy = parameters.strategy
                self.parameters.population = parameters.population
                self.parameters.loss_values = parameters.loss_values
        except Exception as error:
            logger.warning(f"{error=} while loading {self.bot_config.params_path}")

        if self.bot_config.training:
            logger.info("Sampling bot parameters")
            self.parameters.ask()
        else:
            self.parameters.ask_best()
        logger.info(f"{self.parameters.parameters=}")

        def handle_message(message):
            severity = message.record["level"]
            self.add_replay_tag(f"log_{severity.name.lower()}")

        logger.add(handle_message, level=self.bot_config.tag_log_level, enqueue=True)

        if self.version:
            self.add_replay_tag(f"version_{self.version}")

        if self.bot_config.save_bot_path:
            output_path = os.path.join(self.bot_config.save_bot_path, f"{self.game_info.map_name}.xz")
            logger.info(f"Saving game info to {output_path=}")
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            export = await self.export()
            with lzma.open(output_path, "wb") as f:
                pickle.dump(export, f)

    async def on_step(self, iteration: int):
        await super().on_step(iteration)

        # await self.client.save_replay(self.client.save_replay_path)

        # local only: skip first iteration like on the ladder
        if iteration == 0:
            return

        self.structure_dict.clear()
        self.structure_dict.update({tuple(s.position.rounded): s for s in self.structures})
        for plan in self.agent.macro.enumerate_plans():
            if plan.item in ALL_STRUCTURES and plan.target:
                self.structure_dict[tuple(plan.target.position.rounded)] = plan
        for ordered in self.ordered_structures.values():
            if ordered.type in ALL_STRUCTURES:
                self.structure_dict[ordered.position.rounded] = ordered

        # if self.time > 5 * 60:
        #     await self.client.debug_kill_unit(self.structures)

        # await self.client.save_replay("tmp.SC2Replay")
        # cheat = Replay.from_file("tmp.SC2Replay")
        # cheat_state = cheat.steps[max(cheat.steps.keys())]
        # logger.debug(str(cheat_state.player_compositions()[2]))

        if self.bot_config.resign_after_iteration is not None and self.bot_config.resign_after_iteration < iteration:
            logger.info(f"Reached iteration {self.bot_config.resign_after_iteration}, resigning.")
            await self.client.debug_kill_unit(self.structures)
            # await self.client.leave()

        for error in self.state.action_errors:
            logger.warning(f"{error=}")

        if self.bot_config.debug_draw:
            all_plans = [
                *[(None, p) for p in self.agent.macro.unassigned_plans],
                *self.agent.macro.assigned_plans.items(),
            ]
            plans_sorted = sorted(all_plans, key=lambda p: p[1].priority, reverse=True)
            for i, (t, plan) in enumerate(plans_sorted):
                self._debug_draw_plan(self.unit_tag_dict.get(t), plan, index=i)

        if self.bot_config.profile_path:
            self.profiler.enable()

        self.actions_by_ability.clear()
        for action in self.state.actions_unit_commands:
            self.actions_by_ability[action.exact_id].append(action)
            for tag in action.unit_tags:
                self.handle_action(action, tag)

        self.workers_in_gas_buildings.clear()
        for tag, unit in list(self.worker_memory.items()):
            if new_unit := self.unit_tag_dict.get(tag):
                self.worker_memory[tag] = new_unit
            elif ordered_structure := self.ordered_structures.get(tag):
                # the drone morphed into something
                self.worker_memory.pop(tag, None)
            else:
                # the worker entered a geyser, nydus or dropperlord
                self.workers_in_gas_buildings[tag] = unit

        # track ordered structures
        for tag, ordered_structure in list(self.ordered_structures.items()):
            if unit := self.unit_tag_dict.get(tag):
                ability = TRAIN_INFO[unit.type_id][ordered_structure.type]["ability"]
                if not unit.is_using_ability(ability):
                    logger.warning(f"{unit=} is doing {unit.orders} and not as {ordered_structure=}")
                    del self.ordered_structures[tag]
            else:
                logger.info(f"Trainer {tag=} is MIA for {ordered_structure=}")
                del self.ordered_structures[tag]
        self.ordered_structure_position_to_tag = {s.position: tag for tag, s in self.ordered_structures.items()}

        self.actual_by_type = Counter[UnitTypeId](
            u.type_id for u in self.all_own_units if u.is_ready or u.tag in self.units_completed_this_frame
        )
        self.actual_by_type[UnitTypeId.DRONE] = int(self.supply_workers)
        self.pending_by_type = Counter[UnitTypeId](self.pending.values())
        self.ordered_by_type = Counter[UnitTypeId](s.type for s in self.ordered_structures.values())
        self.townhall_at = {tuple(b.position.rounded): b for b in self.townhalls}
        self.resource_at = {tuple(r.position.rounded): r for r in self.resources}

        self.bases_taken = set[tuple[int, int]]()
        if not self.is_micro_map:
            self.bases_taken.update(b for b in self.bases if (th := self.townhall_at.get(b)) and th.is_ready)

        self.all_taken_resources = Units(
            [
                r
                for base in self.bases
                if (th := self.townhall_at.get(base)) and th.is_ready
                for p in self.expansion_resource_positions[base]
                if (r := self.resource_at.get(p))
            ],
            self,
        )
        self.max_harvesters = sum(
            (
                2 * self.all_taken_resources.mineral_field.amount,
                3 * self.gas_buildings.amount,
                # 22 * self.townhalls.not_ready.amount,
            )
        )

        self.supply_pending = 0
        self.supply_income = 0.0
        for unit_type, provided in SUPPLY_PROVIDED[self.race].items():
            total_provided = provided * self.count_pending(unit_type)
            self.supply_pending += total_provided
            self.supply_income += total_provided / self.build_time(unit_type)

        larva_income = sum(
            sum(
                (
                    1 / 11 if h.is_ready else 0.0,
                    3 / 29 if h.has_buff(BuffId.QUEENSPAWNLARVATIMER) else 0.0,  # TODO: track actual injects
                )
            )
            for h in self.townhalls
        )
        self.income = Cost(
            self.state.score.collection_rate_minerals / 60.0,  # TODO: get from harvest assignment
            self.state.score.collection_rate_vespene / 60.0,  # TODO: get from harvest assignment
            self.supply_income,  # TODO: iterate over pending
            larva_income,
        )

        self.bank = Cost(self.minerals, self.vespene, self.supply_left, self.larva.amount)

        self.planned = Counter(p.item for p in self.agent.macro.enumerate_plans())

        actions = self.agent.step()

        for unit, action in actions.items():
            if not await action.execute(unit):
                self.add_replay_tag("action_failed")
                logger.error(f"Action failed: {action}")

        if self.bot_config.profile_path:
            self.profiler.disable()

            if self.actual_iteration % 100 == 0:
                logger.info(f"Writing profiling to {self.bot_config.profile_path}")

                s = io.StringIO()
                stats = pstats.Stats(self.profiler, stream=s)
                stats = stats.strip_dirs().sort_stats(pstats.SortKey.CUMULATIVE)
                stats.print_callers()
                with open(self.bot_config.profile_path + ".callers", "w+") as f:
                    f.write(s.getvalue())

                s = io.StringIO()
                stats = pstats.Stats(self.profiler, stream=s)
                stats = stats.strip_dirs().sort_stats(pstats.SortKey.CUMULATIVE)
                stats.print_callees()
                with open(self.bot_config.profile_path + ".callees", "w+") as f:
                    f.write(s.getvalue())

                stats = pstats.Stats(self.profiler)
                stats = stats.strip_dirs().sort_stats(pstats.SortKey.CUMULATIVE)
                stats.dump_stats(filename=self.bot_config.profile_path)

        try:
            tag = self.replay_tag_queue.get(block=False)
            await self._send_replay_tag(tag)
        except Empty:
            pass

        self.units_completed_this_frame.clear()

    async def on_end(self, game_result: Result):
        await super().on_end(game_result)

        if self.agent and self.bot_config.training:
            fitness = self.get_fitness_value()
            logger.info(f"Training parameters with {fitness=}")
            self.parameters.tell(fitness)
            with lzma.open(self.bot_config.params_path, "wb") as f:
                pickle.dump(self.parameters, f)

    def get_fitness_value(self, vespene_weight: float = 2.0) -> float:
        def sum_category(category: CategoryScoreDetails) -> float:
            return sum(
                (
                    category.army,
                    category.economy,
                    category.none,
                    category.technology,
                    category.upgrade,
                )
            )

        lost_minerals = sum(
            (
                sum_category(self.state.score._proto.lost_minerals),
                sum_category(self.state.score._proto.friendly_fire_minerals),
            )
        )
        lost_vespene = sum(
            (
                sum_category(self.state.score._proto.lost_vespene),
                sum_category(self.state.score._proto.friendly_fire_vespene),
            )
        )
        lost_total = lost_minerals + lost_vespene * vespene_weight

        killed_minerals = sum_category(self.state.score._proto.killed_minerals)
        killed_vespene = sum_category(self.state.score._proto.killed_vespene)
        killed_total = killed_minerals + killed_vespene * vespene_weight

        return killed_total / max(1.0, lost_total + killed_total)

    # async def on_before_start(self):
    #     await super().on_before_start()
    #
    async def on_building_construction_started(self, unit: Unit):
        logger.info(f"on_building_construction_started {unit=}")
        await super().on_building_construction_started(unit)
        self.agent.on_building_construction_started(unit)
        if ordered_from := self.ordered_structure_position_to_tag.get(unit.position):
            self.ordered_structures.pop(ordered_from, None)
            self.worker_memory.pop(ordered_from, None)
        else:
            logger.info(f"{unit=} was started before being ordered")
        self.pending[unit.tag] = unit.type_id

    async def on_building_construction_complete(self, unit: Unit):
        self.units_completed_this_frame.add(unit.tag)
        exists = unit.tag not in self._structures_previous_map
        logger.info(f"on_building_construction_complete {unit=}, {exists=}")
        await super().on_building_construction_complete(unit)
        if unit.type_id in {UnitTypeId.LAIR, UnitTypeId.HIVE, UnitTypeId.GREATERSPIRE, UnitTypeId.CREEPTUMORBURROWED}:
            return
        if unit.tag not in self.pending:
            logger.error("unit not found")
        del self.pending[unit.tag]

    # async def on_enemy_unit_entered_vision(self, unit: Unit):
    #     await super().on_enemy_unit_entered_vision(unit)
    #
    # async def on_enemy_unit_left_vision(self, unit_tag: int):
    #     await super().on_enemy_unit_left_vision(unit_tag)
    #
    async def on_unit_destroyed(self, unit_tag: int):
        logger.info(f"on_unit_destroyed {unit_tag=}")
        await super().on_unit_destroyed(unit_tag)
        self.pending.pop(unit_tag, None)
        self.pending_upgrades.pop(unit_tag, None)
        self.worker_memory.pop(unit_tag, None)
        # if unit := (self._units_previous_map.get(unit_tag) or self._structures_previous_map.get(unit_tag)):
        #     for order in unit.orders:
        #         ability = order.ability.exact_id
        #         if item := UPGRADE_BY_RESEARCH_ABILITY.get(ability):
        #             self.pending_upgrades.remove(item)

    async def on_unit_created(self, unit: Unit):
        await super().on_unit_created(unit)
        if unit.type_id in WORKER_TYPES:
            self.worker_memory[unit.tag] = unit

    async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId):
        self.units_completed_this_frame.add(unit.tag)
        self.agent.on_unit_type_changed(unit, previous_type)
        logger.info(f"on_unit_type_changed {unit=} {previous_type=}")
        await super().on_unit_type_changed(unit, previous_type)
        if unit.type_id == UnitTypeId.EGG:
            self.pending[unit.tag] = ITEM_BY_ABILITY[unit.orders[0].ability.exact_id]
        elif unit.is_structure and unit.type_id not in {UnitTypeId.CREEPTUMORBURROWED}:
            del self.pending[unit.tag]

    #
    # async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float):
    #     await super().on_unit_took_damage(unit, amount_damage_taken)
    #
    async def on_upgrade_complete(self, upgrade: UpgradeId):
        logger.info(f"on_upgrade_complete {upgrade=}")
        await super().on_upgrade_complete(upgrade)
        researcher = next((t for t, u in self.pending_upgrades.items() if u == upgrade), None)
        if researcher:
            del self.pending_upgrades[researcher]
        else:
            logger.error(f"No researcher for {upgrade=}")

    def handle_action(self, action: ActionRawUnitCommand, tag: int) -> None:
        unit = self.unit_tag_dict.get(tag) or self._units_previous_map.get(tag)
        if not (item := ITEM_BY_ABILITY.get(action.exact_id)):
            return
        if (
            action.exact_id == AbilityId.BUILD_CREEPTUMOR_QUEEN
            or action.exact_id == AbilityId.SPAWNCHANGELING_SPAWNCHANGELING
        ):
            pass
        else:
            lookup_tag = tag
            if unit and unit.type_id == UnitTypeId.EGG:
                # commands issued to a specific larva will be received by a random one
                # therefore, a direct lookup will often be incorrect
                # instead, all plans are checked for a match
                for t, p in self.agent.macro.assigned_plans.items():
                    if item == p.item:
                        if tag != t:
                            logger.info(f"Correcting morph tag from {tag} to {t=}")
                            lookup_tag = t
                        break
            if plan := self.agent.macro.assigned_plans.get(lookup_tag):
                if item != plan.item:
                    logger.info(f"{action=} for {item=} does not match {plan=}")
                else:
                    del self.agent.macro.assigned_plans[lookup_tag]
                    if isinstance(item, UpgradeId):
                        self.pending_upgrades[lookup_tag] = item
                    elif item in ALL_STRUCTURES and (
                        "requires_placement_position" in TRAIN_INFO[unit.type_id][item] or item == UnitTypeId.EXTRACTOR
                    ):
                        if tag in self.unit_tag_dict:
                            if isinstance(unit.order_target, Point2):
                                self.ordered_structures[tag] = OrderedStructure(item, unit.order_target)
                            elif isinstance(unit.order_target, int):
                                self.ordered_structures[tag] = OrderedStructure(
                                    item, self.unit_tag_dict[unit.order_target].position
                                )
                        else:
                            logger.info("ordered unit not found, assuming it was a drone morphing")
                            self.worker_memory.pop(tag, None)
                    else:
                        logger.info(f"Pending {item=} through {tag=}, {unit=}")
                        self.pending[tag] = item
                    logger.info(f"Executed {plan=} through {action}")
            elif action.exact_id in ALL_MACRO_ABILITIES:
                logger.info(f"Unplanned {action=}")

    @property
    def name(self) -> str:
        return self.__class__.__name__

    def pick_race(self) -> Race:
        return Race.Zerg

    def _debug_draw_plan(
        self,
        unit: Unit | None,
        plan: MacroPlan,
        index: int,
        font_color=(255, 255, 255),
        font_size=16,
    ) -> None:
        positions = []
        if isinstance(plan.target, Unit):
            positions.append(plan.target.position3d)
        elif isinstance(plan.target, Point3):
            positions.append(plan.target)
        elif isinstance(plan.target, Point2):
            height = self.get_terrain_z_height(plan.target)
            positions.append(Point3((plan.target.x, plan.target.y, height)))

        if unit:
            height = self.get_terrain_z_height(unit)
            positions.append(Point3((unit.position.x, unit.position.y, height)))

        text = f"{plan.item.name} {round(plan.priority, 2)}"

        for position in positions:
            self.client.debug_text_world(text, position, color=font_color, size=font_size)

        if len(positions) == 2:
            position_from, position_to = positions
            position_from += Point3((0.0, 0.0, 0.1))
            position_to += Point3((0.0, 0.0, 0.1))
            self.client.debug_line_out(position_from, position_to, color=font_color)

        self.client.debug_text_screen(
            f"{1 + index} {round(plan.priority, 2)} {plan.item.name}", (0.01, 0.1 + 0.01 * index)
        )

    async def _send_replay_tag(self, replay_tag: str) -> None:
        if replay_tag in self.replay_tags:
            return
        logger.info(f"Adding {replay_tag=}")
        self.replay_tags.add(replay_tag)
        await self.client.chat_send(f"Tag:{replay_tag}", True)

    def build_time(self, t: UnitTypeId) -> float:
        return self.game_data.units[t.value].cost.time

    @property_cache_once_per_frame
    def visibility_grid(self) -> np.ndarray:
        return np.equal(self.state.visibility.data_numpy.T, 2.0)

    def send_overlord_scout(self) -> None:
        scout_overlord = self.units(UnitTypeId.OVERLORD)[0]
        scout_path = list[Point2]()
        sight_range = scout_overlord.sight_range
        townhall_size = self.townhalls[0].radius - 1.0
        worker_speed = self.workers[0].movement_speed
        sensitivity = int(sight_range)
        rush_path = self.mediator.find_raw_path(
            start=self.start_location,
            target=self.enemy_start_locations[0],
            grid=self.mediator.get_cached_ground_grid,
            sensitivity=sensitivity,
        )
        for p in rush_path:
            overlord_duration = (
                cy_distance_to(scout_overlord.position, p) - sight_range
            ) / scout_overlord.movement_speed
            worker_duration = cy_distance_to(self.enemy_start_locations[0], p) / worker_speed
            if overlord_duration < worker_duration:
                continue
            if cy_distance_to(p, self.mediator.get_enemy_nat) < sight_range + townhall_size:
                break
            if cy_distance_to(p, self.mediator.get_enemy_ramp.barracks_correct_placement) < sight_range:
                break
            scout_path.append(p)
        nat_scout_point = self.mediator.get_enemy_nat.towards(scout_path[-1], TOWNHALL_RADIUS + sight_range)
        scout_path.append(nat_scout_point)
        if self.enemy_race in {Race.Zerg, Race.Random}:
            safe_spot = rush_path[len(rush_path) // 2]
        else:
            safe_spot = self.mediator.get_ol_spot_near_enemy_nat
        scout_path.append(safe_spot)
        for overlord in self.units(UnitTypeId.OVERLORD):
            for p in scout_path:
                overlord.move(p, queue=True)

    def can_move(self, unit: Unit) -> bool:
        if unit.is_burrowed:
            if unit.type_id == UnitTypeId.INFESTORBURROWED:
                return True
            elif unit.type_id == UnitTypeId.ROACHBURROWED:
                return UpgradeId.TUNNELINGCLAWS in self.state.upgrades
            return False
        return unit.movement_speed > 0

    def upgrades_by_unit(self, unit: UnitTypeId) -> Iterable[UpgradeId]:
        if unit == UnitTypeId.ZERGLING:
            return chain(
                # (UpgradeId.ZERGLINGMOVEMENTSPEED,),
                (UpgradeId.ZERGLINGMOVEMENTSPEED, UpgradeId.ZERGLINGATTACKSPEED),
                self.upgrade_sequence(ZERG_MELEE_UPGRADES),
                self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
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
        elif unit in (UnitTypeId.MUTALISK, UnitTypeId.CORRUPTOR):
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

    def upgrade_sequence(self, upgrades) -> Iterable[UpgradeId]:
        for upgrade in upgrades:
            if upgrade in self.state.upgrades:
                continue
            if upgrade in self.pending_upgrades.values():
                continue
            return (upgrade,)
        return ()

    def random_point(self, near: Point2 | None) -> Point2:
        a = self.game_info.playable_area
        scale = min(self.game_info.map_size) / 5
        if near:
            target = np.clip(
                RNG.normal((near.x, near.y), scale),
                (0.0, 0.0),
                (a.right, a.top),
            )
        else:
            target = RNG.uniform((a.x, a.y), (a.right, a.top))
        return Point2(target)

    def is_unit_missing(self, unit: UnitTypeId) -> bool:
        if unit in {
            UnitTypeId.LARVA,
        }:
            return False
        return all(self.count_actual(e) == 0 for e in WITH_TECH_EQUIVALENTS[unit])

    def count_actual(self, item: UnitTypeId) -> int:
        return self.actual_by_type[item]

    def count_pending(self, item: UnitTypeId) -> int:
        factor = 2 if item == UnitTypeId.ZERGLING else 1
        return factor * (self.pending_by_type[item] + self.ordered_by_type[item])

    def count_planned(self, item: MacroId) -> int:
        factor = 2 if item == UnitTypeId.ZERGLING else 1
        return factor * self.planned[item]

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

        # if self.is_unit_missing(trainer):
        #     yield trainer
        yield from self.get_missing_requirements(trainer)
        if (required_building := info.get("required_building")) and self.is_unit_missing(required_building):
            yield required_building
        if (
            (required_upgrade := info.get("required_upgrade"))
            and isinstance(required_upgrade, UpgradeId)
            and required_upgrade not in self.state.upgrades
        ):
            yield required_upgrade

    @property_cache_once_per_frame
    def blocked_positions(self) -> Set[Point2]:
        return set(self.agent.scout.blocked_positions)
