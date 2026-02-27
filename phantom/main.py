import cProfile
import io
import os
import pstats
from collections import Counter, defaultdict
from collections.abc import Iterable, Set
from dataclasses import dataclass
from itertools import chain

import numpy as np
from ares import AresBot
from ares.consts import ALL_STRUCTURES, CREEP_TUMOR_TYPES
from loguru import logger
from sc2.cache import property_cache_once_per_frame
from sc2.data import Race, Result
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
from phantom.common.config import BotConfig
from phantom.common.constants import (
    DESTRUCTABLE_SIZE,
    ITEM_BY_ABILITY,
    PENDING_UNIT_TYPES,
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
from phantom.common.damage_tracker import DamageTracker
from phantom.common.expansion import Expansion
from phantom.common.point import to_point
from phantom.common.utils import (
    RNG,
    MacroId,
    Point,
)
from phantom.macro.builder import MacroPlan
from phantom.observation import Observation, build_observation


@dataclass(frozen=True)
class OrderedStructure:
    type: UnitTypeId
    position: Point2


class PhantomBot(AresBot):
    def __init__(self, config: BotConfig, opponent_id: str, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self.bot_config = config
        self.opponent_id = opponent_id
        self._replay_tags_sent = set[str]()
        self._replay_tags_unsent = list[str]()
        self.version: str | None = None
        self.profiler = cProfile.Profile()
        self.pending = dict[int, MacroId]()
        self.units_completed_this_frame = set[int]()
        self.cost = CostManager(self)
        self.worker_memory = dict[int, Unit]()
        self.workers_off_map = dict[int, Unit]()
        self.actions_by_ability = defaultdict[AbilityId, list[UnitCommand]](list)
        self.expansions = dict[Point, Expansion]()
        self.structure_dict = dict[Point, Unit | OrderedStructure | MacroPlan]()
        self._blocked_positions = set[Point]()
        self.damage_tracker = DamageTracker()
        self.enemy_race_initial = Race.NoRace

        self._setup_logging()
        self._read_version()

    async def on_before_start(self) -> None:
        await super().on_before_start()

    async def on_start(self) -> None:
        await super().on_start()
        logger.info("on_start")
        await self._initialize_map()
        self.agent = Agent(self, self.bot_config)
        self.enemy_race_initial = self.enemy_race

        # await self.client.debug_create_unit([
        #     [UnitTypeId.ZERGLING, 7, self.game_info.map_center, 1],
        #     [UnitTypeId.MARINE, 4, self.game_info.map_center, 2],
        # ])

    async def on_step(self, iteration: int):
        await super().on_step(iteration)
        if self.bot_config.profile_path:
            self.profiler.enable()

        self._update_tables()
        observation = self.observe()
        actions = await self.agent.on_step(observation)
        for unit, action in actions.items():
            await action.execute(unit)

        if self.bot_config.profile_path:
            self.profiler.disable()
            if self.actual_iteration % self.bot_config.profile_interval == 0:
                self._write_profile(self.bot_config.profile_path)

        await self._send_replay_tags()
        self.units_completed_this_frame.clear()

    async def on_end(self, game_result: Result):
        await super().on_end(game_result)
        self.agent.on_end(game_result)

    async def on_building_construction_started(self, unit: Unit) -> None:
        if unit.type_id not in CREEP_TUMOR_TYPES:
            logger.info(f"on_building_construction_started {unit}")
        await super().on_building_construction_started(unit)

    async def on_building_construction_complete(self, unit: Unit) -> None:
        self.units_completed_this_frame.add(unit.tag)
        if unit.type_id not in CREEP_TUMOR_TYPES:
            logger.info(f"on_building_construction_complete {unit}")
        await super().on_building_construction_complete(unit)

    async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId) -> None:
        self.units_completed_this_frame.add(unit.tag)
        self.agent.on_unit_type_changed(unit, previous_type)
        await super().on_unit_type_changed(unit, previous_type)

    async def on_enemy_unit_entered_vision(self, unit: Unit) -> None:
        await super().on_enemy_unit_entered_vision(unit)

    async def on_enemy_unit_left_vision(self, unit_tag: int) -> None:
        await super().on_enemy_unit_left_vision(unit_tag)

    async def on_unit_destroyed(self, unit_tag: int) -> None:
        await super().on_unit_destroyed(unit_tag)

    async def on_unit_created(self, unit: Unit) -> None:
        if hasattr(self, "agent"):
            self.agent.on_unit_created(unit)
        await super().on_unit_created(unit)

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float) -> None:
        await super().on_unit_took_damage(unit, amount_damage_taken)
        self.damage_tracker.on_unit_took_damage(unit, amount_damage_taken)

    async def on_upgrade_complete(self, upgrade: UpgradeId) -> None:
        await super().on_upgrade_complete(upgrade)

    def add_replay_tag(self, replay_tag: str) -> None:
        self._replay_tags_unsent.append(replay_tag)

    async def _send_replay_tags(self) -> None:
        tags_to_send = set(self._replay_tags_unsent) - self._replay_tags_sent
        for tag in tags_to_send:
            logger.info(f"Adding {tag=}")
            self._replay_tags_sent.add(tag)
            await self.client.chat_send(f"Tag:{tag}", True)
        self._replay_tags_unsent.clear()

    @property
    def harvesters_per_mineral_field(self) -> int:
        return 2

    @property
    def harvesters_per_gas_building(self) -> int:
        if self.researched_speed:
            return 2
        else:
            return 3

    @property_cache_once_per_frame
    def researched_speed(self) -> bool:
        return (
            self.count_actual(UpgradeId.ZERGLINGMOVEMENTSPEED) > 0
            or self.count_pending(UpgradeId.ZERGLINGMOVEMENTSPEED) > 0
            # or self.vespene >= 96
        )

    @property_cache_once_per_frame
    def income(self) -> Cost:
        supply_income = 0.0
        for unit_type, provided in SUPPLY_PROVIDED[self.race].items():
            build_time = self.game_data.units[unit_type.value].cost.time
            total_provided = provided * self.count_pending(unit_type)
            supply_income += total_provided / build_time

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
                self.upgrade_sequence(ZERG_RANGED_UPGRADES),
                self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.HYDRALISK:
            return chain(
                (UpgradeId.EVOLVEGROOVEDSPINES, UpgradeId.EVOLVEMUSCULARAUGMENTS),
                self.upgrade_sequence(ZERG_RANGED_UPGRADES),
                self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
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
        if unit == UnitTypeId.LARVA:
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
        return factor * int(isinstance(item, UnitTypeId) and self.agent.builder.is_planned(item))

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
    def blocked_positions(self) -> Set[Point]:
        return set(self._blocked_positions)

    def is_on_edge_of_creep(self, p: Point | Point2 | Unit) -> bool:
        if isinstance(p, tuple):
            q = p
        elif isinstance(p, Point2):
            q = to_point(p)
        elif isinstance(p, Unit):
            q = to_point(p.position)
        else:
            raise TypeError(p)
        x, y = q
        xs = [x, x, x, x - 1, x + 1]
        ys = [y, y - 1, y + 1, y, y]
        creep_values = self.mediator.get_creep_grid[ys, xs]
        pathing_values = self.mediator.get_cached_ground_grid[xs, ys]
        check_values = {int(c) for c, p in zip(creep_values, pathing_values, strict=True) if p < np.inf}
        return check_values.issuperset({0, 1})

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

    def _setup_logging(self) -> None:
        def handle_message(message):
            severity = message.record["level"]
            self.add_replay_tag(f"log_{severity.name.lower()}")

        logger.add(handle_message, level=self.bot_config.tag_log_level, enqueue=True)

    def _read_version(self) -> None:
        if os.path.isfile(self.bot_config.version_path):
            logger.info(f"Reading version from {self.bot_config.version_path}")
            with open(self.bot_config.version_path) as f:
                self.version = f.read()
        else:
            logger.warning(f"Version not found: {self.bot_config.version_path}")
        if self.version:
            self.add_replay_tag(f"version_{self.version}")

    async def _initialize_map(self) -> None:
        # for b in self.expansion_locations_list:
        #     if not await self.can_place_single(UnitTypeId.HATCHERY, b):
        #         print(b, await self.find_placement(UnitTypeId.HATCHERY, b, placement_step=1))
        self.expansions = {
            to_point(p): Expansion.from_resources(p, resources)
            for p, resources in self.expansion_locations_dict.items()
        }
        # fix invalid townhall positions
        for b, e in list(self.expansions.items()):
            if e.townhall_position != self.start_location and not await self.can_place_single(
                UnitTypeId.HATCHERY, e.townhall_position
            ):
                if fixed := await self.find_placement(
                    UnitTypeId.HATCHERY, e.townhall_position, max_distance=2, placement_step=1
                ):
                    self.expansions[b].townhall_position = fixed
                else:
                    del self.expansions[b]

        self.gather_targets = dict(p for e in self.expansions.values() for p in e.gather_targets.items())
        self.return_distances = dict(p for e in self.expansions.values() for p in e.return_distances.items())

    def _update_tables(self) -> None:
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
        trainers = self.all_own_units(PENDING_UNIT_TYPES)
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
        for plan in self.agent.builder.plans().values():
            if plan.target:
                self.structure_dict[to_point(plan.target.position)] = plan

        self.actual_by_type = Counter[UnitTypeId](
            u.type_id for u in self.all_own_units if u.is_ready or u.tag in self.units_completed_this_frame
        )
        self.actual_by_type[UnitTypeId.DRONE] = int(self.supply_workers)
        self.pending_by_type = Counter[UnitTypeId](self.pending.values())

        resources_at = {to_point(r.position): r for r in self.resources}

        self.bases_taken = {
            b: e
            for b, e in self.expansions.items()
            if isinstance(th := self.structure_dict.get(b), Unit) and th.is_ready
        }

        self.all_taken_minerals = [
            r for base in self.bases_taken.values() for p in base.mineral_positions if (r := resources_at.get(p))
        ]
        self.all_taken_geysers = [
            r for base in self.bases_taken.values() for p in base.geyser_positions if (r := resources_at.get(p))
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

    def observe(self) -> Observation:
        return build_observation(self)

    def set_blocked_positions(self, blocked_positions: Set[Point]) -> None:
        self._blocked_positions = set(blocked_positions)

    @property_cache_once_per_frame
    def ground_grid(self) -> np.ndarray:
        grid = self.mediator.get_ground_grid
        self._add_nonpathables(grid)
        return grid

    @property_cache_once_per_frame
    def clean_ground_grid(self) -> np.ndarray:
        grid = self.mediator.get_cached_ground_grid
        self._add_nonpathables(grid)
        return grid

    def _add_nonpathables(self, grid: np.ndarray) -> None:
        """Add some special nonpathables not handled by mapanalyzer."""
        for destructable in self.destructables:
            if size := DESTRUCTABLE_SIZE.get(destructable.type_id):
                width, height = size
                x0, y0 = to_point(destructable.position.offset((-width / 2, -height / 2)))
                x1, y1 = x0 + width, y0 + height
                grid[x0:x1, y0:y1] = np.inf
