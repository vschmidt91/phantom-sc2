import cProfile
import io
import lzma
import os
import pickle
import pstats
from collections import Counter, defaultdict
from collections.abc import Iterable, Set
from dataclasses import dataclass
from itertools import chain

import numpy as np
from ares import AresBot
from ares.behaviors.macro.mining import TOWNHALL_RADIUS
from ares.consts import ALL_STRUCTURES
from cython_extensions import cy_distance_to
from loguru import logger
from s2clientprotocol.score_pb2 import CategoryScoreDetails
from sc2.cache import property_cache_once_per_frame
from sc2.data import ActionResult, Race, Result
from sc2.dicts.unit_research_abilities import RESEARCH_INFO
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.unit_command import UnitCommand

from phantom.agent import Agent
from phantom.common.constants import (
    ITEM_BY_ABILITY,
    MINING_RADIUS,
    REQUIREMENTS_KEYS,
    SUPPLY_PROVIDED,
    TRAINER_TYPES,
    WITH_TECH_EQUIVALENTS,
    ZERG_ARMOR_UPGRADES,
    ZERG_FLYER_ARMOR_UPGRADES,
    ZERG_FLYER_UPGRADES,
    ZERG_MELEE_UPGRADES,
    ZERG_RANGED_UPGRADES,
)
from phantom.common.cost import Cost, CostManager
from phantom.common.utils import (
    RNG,
    MacroId,
    Point,
    get_intersections,
    project_point_onto_line,
    rectangle_perimeter,
    to_point,
)
from phantom.config import BotConfig
from phantom.macro.main import MacroPlan
from phantom.parameter_sampler import ParameterSampler


@dataclass(frozen=True)
class OrderedStructure:
    type: UnitTypeId
    position: Point2


class PhantomBot(AresBot):
    def __init__(self, config: BotConfig, opponent_id: str, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self.bot_config = config
        self.opponent_id = opponent_id
        self.replay_tags = set[str]()
        self.replay_tag_queue = set[str]()
        self.version: str | None = None
        self.profiler = cProfile.Profile()
        self.pending = dict[int, MacroId]()
        self.units_completed_this_frame = set[int]()
        self.parameters = ParameterSampler()
        self.cost = CostManager(self)
        self.worker_memory = dict[int, Unit]()
        self.workers_off_map = dict[int, Unit]()
        self.actions_by_ability = defaultdict[AbilityId, list[UnitCommand]](list)
        self.expansion_mineral_positions = dict[Point, list[Point]]()
        self.expansion_geyser_positions = dict[Point, list[Point]]()
        self.expansion_mineral_center = dict[Point, Point]()
        self.return_point = dict[Point, Point2]()
        self.spore_position = dict[Point, Point]()
        self.spine_position = dict[Point, Point]()
        self.speedmining_positions = dict[Point, Point2]()
        self.return_distances = dict[Point, float]()
        self.enemy_start_locations_rounded = list[Point]()
        self.bases = list[Point]()
        self.structure_dict = dict[Point, Unit | OrderedStructure | MacroPlan]()

        if os.path.isfile(self.bot_config.version_path):
            logger.info(f"Reading version from {self.bot_config.version_path}")
            with open(self.bot_config.version_path) as f:
                self.version = f.read()
        else:
            logger.warning(f"Version not found: {self.bot_config.version_path}")

    def add_replay_tag(self, replay_tag: str) -> None:
        self.replay_tag_queue.add(replay_tag)

    async def on_before_start(self) -> None:
        await super().on_before_start()

    async def on_start(self) -> None:
        await super().on_start()

        logger.info("on_start")
        self.start_location_rounded = to_point(self.start_location)
        self.enemy_start_locations_rounded.extend(map(to_point, self.enemy_start_locations))
        self.bases.extend(map(to_point, self.expansion_locations_list))

        worker_radius = self.workers[0].radius
        for base_position, resources in self.expansion_locations_dict.items():
            b = to_point(base_position)
            self.expansion_mineral_positions[b] = list[Point]()
            self.expansion_geyser_positions[b] = list[Point]()
            for geyser in resources.vespene_geyser:
                p = to_point(geyser.position)
                self.expansion_geyser_positions[b].append(p)
                target = geyser.position.towards(base_position, geyser.radius + worker_radius)
                self.speedmining_positions[p] = target
            for patch in resources.mineral_field:
                p = to_point(patch.position)
                self.expansion_mineral_positions[b].append(p)
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
                self.speedmining_positions[to_point(patch.position)] = target

            mineral_center = Point2(np.mean(self.expansion_mineral_positions[b], axis=0))
            perimeter_start = np.subtract(base_position, 3).astype(int)
            perimeter_end = np.add(base_position, 4).astype(int)
            spore_position = min(
                rectangle_perimeter(perimeter_start, perimeter_end), key=lambda p: cy_distance_to(p, mineral_center)
            )
            self.spore_position[b] = spore_position
            self.spine_position[b] = to_point(
                self.mediator.find_path_next_point(
                    start=base_position,
                    target=self.enemy_start_locations[0],
                    grid=self.mediator.get_cached_ground_grid,
                    sensitivity=5,
                    sense_danger=False,
                )
            )

            for r in resources:
                p = to_point(r.position)
                ps = self.speedmining_positions[p]
                return_point = base_position.towards(ps, 3.125)
                self.return_point[p] = return_point
                self.return_distances[p] = ps.distance_to(return_point)

            self.expansion_mineral_center[b] = to_point(mineral_center)

        self.agent = Agent(self, self.bot_config.build_order, self.parameters)

        self.send_overlord_scout()

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

    async def on_step(self, iteration: int):
        await super().on_step(iteration)

        # local only: skip first iteration like on the ladder
        if iteration == 0:
            return

        if self.bot_config.resign_after_iteration is not None and self.bot_config.resign_after_iteration < iteration:
            logger.info(f"Reached iteration {self.bot_config.resign_after_iteration}, resigning.")
            await self.client.debug_kill_unit(self.structures)

        for error in self.state.action_errors:
            result = ActionResult(error.result)
            logger.info(f"{error} with {result}")

        if self.bot_config.debug_draw:
            self.agent.macro.debug_draw_plans()

        if self.bot_config.profile_path:
            self.profiler.enable()

        self.actions_by_ability.clear()
        for action in self.state.actions_unit_commands:
            self.actions_by_ability[action.exact_id].append(action)

        self.workers_off_map.clear()
        self.worker_memory.update({u.tag: u for u in self.workers})
        for tag, unit in list(self.worker_memory.items()):
            memory_age = self.state.game_loop - unit.game_loop
            if tag in self.unit_tag_dict:
                pass
            elif tag in self.state.dead_units:
                del self.worker_memory[tag]
            elif pending := self.pending.get(tag):
                logger.info(f"{unit} morphed into {pending}")
                del self.worker_memory[tag]
            elif structure := self.structure_dict.get(to_point(unit.position)):
                logger.info(f"{unit} morphed instantly into {structure}")
                del self.worker_memory[tag]
            elif memory_age > 32:
                logger.info(f"{unit} missing for {memory_age} game loops, assuming it is gone")
                del self.worker_memory[tag]
            else:
                # the worker entered a geyser, nydus or dropperlord
                self.workers_off_map[tag] = unit

        self.structure_dict.clear()
        self.pending.clear()
        trainers = self.all_own_units(TRAINER_TYPES)
        for unit in trainers:
            if not unit.is_ready:
                self.pending[unit.tag] = unit.type_id
            elif (order := next(iter(unit.orders), None)) and (item := ITEM_BY_ABILITY.get(order.ability.exact_id)):
                if item in ALL_STRUCTURES:
                    target: Point2 | None = None
                    if isinstance(order.target, Point2):
                        target = order.target
                    elif isinstance(order.target, int):
                        target = None if order.target == 0 else self.unit_tag_dict[order.target].position
                    if target is not None:
                        self.structure_dict[to_point(target)] = OrderedStructure(item, target)
                self.pending[unit.tag] = item

        self.structure_dict.update({to_point(s.position): s for s in self.structures})
        for plan in self.agent.macro.enumerate_plans():
            if plan.item in ALL_STRUCTURES and plan.target:
                self.structure_dict[to_point(plan.target.position)] = plan

        self.actual_by_type = Counter[UnitTypeId](
            u.type_id for u in self.all_own_units if u.is_ready or u.tag in self.units_completed_this_frame
        )
        self.actual_by_type[UnitTypeId.DRONE] = int(self.supply_workers)
        self.pending_by_type = Counter[UnitTypeId](self.pending.values())

        resources_at = {to_point(r.position): r for r in self.resources}

        self.bases_taken = {b for b in self.bases if isinstance(th := self.structure_dict.get(b), Unit) and th.is_ready}

        self.all_taken_minerals = [
            r for base in self.bases_taken for p in self.expansion_mineral_positions[base] if (r := resources_at.get(p))
        ]
        self.all_taken_geysers = [
            r for base in self.bases_taken for p in self.expansion_geyser_positions[base] if (r := resources_at.get(p))
        ]
        self.harvestable_gas_buildings = [
            gas_building
            for geyser in self.all_taken_geysers
            if isinstance(gas_building := self.structure_dict.get(to_point(geyser.position)), Unit)
            and gas_building.is_ready
            and geyser.has_vespene
        ]
        self.max_harvesters = sum(
            (
                self.harvesters_per_mineral_field * len(self.all_taken_minerals),
                self.harvesters_per_gas_building * len(self.harvestable_gas_buildings),
                int(20 * sum(th.build_progress for th in self.townhalls.not_ready)),
            )
        )

        self.bank = Cost(self.minerals, self.vespene, self.supply_left, self.larva.amount)
        self.planned = Counter(p.item for p in self.agent.macro.enumerate_plans())

        actions = self.agent.on_step()

        for unit, action in actions.items():
            if not await action.execute(unit):
                self.add_replay_tag("action_failed")
                logger.error(f"Action failed: {action}")

        if self.bot_config.profile_path:
            self.profiler.disable()
            if self.actual_iteration % self.bot_config.profile_interval == 0:
                self._write_profile(self.bot_config.profile_path)

        for replay_tag in self.replay_tag_queue:
            await self._send_replay_tag(replay_tag)
        self.replay_tag_queue.clear()

        self.units_completed_this_frame.clear()

    async def on_end(self, game_result: Result):
        await super().on_end(game_result)

        if self.agent and self.bot_config.training:
            fitness = self._get_fitness_value()
            logger.info(f"Training parameters with {fitness=}")
            self.parameters.tell(fitness)
            with lzma.open(self.bot_config.params_path, "wb") as f:
                pickle.dump(self.parameters, f)

    #
    async def on_building_construction_started(self, unit: Unit):
        logger.info(f"on_building_construction_started {unit}")
        await super().on_building_construction_started(unit)

    async def on_building_construction_complete(self, unit: Unit):
        self.units_completed_this_frame.add(unit.tag)
        logger.info(f"on_building_construction_complete {unit}")
        await super().on_building_construction_complete(unit)

    async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId):
        self.units_completed_this_frame.add(unit.tag)
        self.agent.on_unit_type_changed(unit, previous_type)
        await super().on_unit_type_changed(unit, previous_type)

    # async def on_before_start(self):
    #     await super().on_before_start()

    # async def on_enemy_unit_entered_vision(self, unit: Unit):
    #     await super().on_enemy_unit_entered_vision(unit)

    # async def on_enemy_unit_left_vision(self, unit_tag: int):
    #     await super().on_enemy_unit_left_vision(unit_tag)
    # #
    # async def on_unit_destroyed(self, unit_tag: int):
    #     await super().on_unit_destroyed(unit_tag)

    # async def on_unit_created(self, unit: Unit):
    #     await super().on_unit_created(unit)

    # async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float):
    #     await super().on_unit_took_damage(unit, amount_damage_taken)

    # async def on_upgrade_complete(self, upgrade: UpgradeId):
    #     await super().on_upgrade_complete(upgrade)

    @property
    def name(self) -> str:
        return self.__class__.__name__

    def pick_race(self) -> Race:
        return Race.Zerg

    async def _send_replay_tag(self, replay_tag: str) -> None:
        if replay_tag in self.replay_tags:
            return
        logger.info(f"Adding {replay_tag=}")
        self.replay_tags.add(replay_tag)
        await self.client.chat_send(f"Tag:{replay_tag}", True)

    def build_time(self, t: UnitTypeId) -> float:
        return self.game_data.units[t.value].cost.time

    @property
    def harvesters_per_mineral_field(self) -> int:
        return 2

    @property_cache_once_per_frame
    def researched_speed(self) -> bool:
        return (
            self.count_actual(UpgradeId.ZERGLINGMOVEMENTSPEED) > 0
            or self.count_pending(UpgradeId.ZERGLINGMOVEMENTSPEED) > 0
            or self.vespene >= 96
        )

    @property_cache_once_per_frame
    def harvesters_per_gas_building(self) -> int:
        if self.researched_speed:
            return 2
        else:
            return 3

    @property_cache_once_per_frame
    def visibility_grid(self) -> np.ndarray:
        return np.equal(self.state.visibility.data_numpy.T, 2.0)

    @property_cache_once_per_frame
    def income(self) -> Cost:
        supply_income = 0.0
        for unit_type, provided in SUPPLY_PROVIDED[self.race].items():
            total_provided = provided * self.count_pending(unit_type)
            supply_income += total_provided / self.build_time(unit_type)

        larva_income = sum(
            sum(
                (
                    1 / 11 if h.is_ready else 0.0,
                    3 / 29 if h.has_buff(BuffId.QUEENSPAWNLARVATIMER) else 0.0,
                )
            )
            for h in self.townhalls
        )
        income = Cost(
            self.state.score.collection_rate_minerals / 60.0,
            self.state.score.collection_rate_vespene / 60.0,
            supply_income,
            larva_income,
        )
        return income

    def send_overlord_scout(self) -> None:
        scout_overlord = self.units(UnitTypeId.OVERLORD)[0]
        scout_path = list[Point2]()
        sight_range = scout_overlord.sight_range
        townhall_size = self.townhalls[0].radius - 1.0
        worker_speed = 1.4 * self.workers[0].real_speed
        overlord_speed = 1.4 * scout_overlord.real_speed
        sensitivity = int(sight_range)
        rush_path = self.mediator.find_raw_path(
            start=self.start_location,
            target=self.enemy_start_locations[0],
            grid=self.mediator.get_cached_ground_grid,
            sensitivity=sensitivity,
        )
        for p in rush_path:
            overlord_duration = (cy_distance_to(scout_overlord.position, p) - sight_range) / overlord_speed
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
            if upgrade not in self.state.upgrades:
                if self.count_pending(upgrade):
                    return []
                else:
                    return [upgrade]
        return []

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

    def count_actual(self, item: MacroId) -> int:
        if isinstance(item, UnitTypeId):
            return self.actual_by_type[item]
        elif isinstance(item, UpgradeId):
            return 1 if item in self.state.upgrades else 0
        else:
            raise TypeError(item)

    def count_pending(self, item: MacroId) -> int:
        factor = 2 if item == UnitTypeId.ZERGLING else 1
        return factor * self.pending_by_type[item]

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

    def _get_fitness_value(self, vespene_weight: float = 2.0) -> float:
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

    def _write_profile(self, path: str) -> None:
        logger.info(f"Writing profiling to {path}")

        s = io.StringIO()
        stats = pstats.Stats(self.profiler, stream=s)
        stats = stats.strip_dirs().sort_stats(pstats.SortKey.CUMULATIVE)
        stats.print_callers()
        with open(path + ".callers", "w+") as f:
            f.write(s.getvalue())

        s = io.StringIO()
        stats = pstats.Stats(self.profiler, stream=s)
        stats = stats.strip_dirs().sort_stats(pstats.SortKey.CUMULATIVE)
        stats.print_callees()
        with open(path + ".callees", "w+") as f:
            f.write(s.getvalue())

        stats = pstats.Stats(self.profiler)
        stats = stats.strip_dirs().sort_stats(pstats.SortKey.CUMULATIVE)
        stats.dump_stats(filename=path)
