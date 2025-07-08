import cProfile
import io
import lzma
import os
import pickle
import pstats
from dataclasses import dataclass
from queue import Empty, Queue

from ares import AresBot
from ares.consts import ALL_STRUCTURES
from loguru import logger
from sc2.data import Race, Result
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.game_state import ActionRawUnitCommand
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2, Point3
from sc2.unit import Unit

from phantom.agent import Agent
from phantom.common.constants import ALL_MACRO_ABILITIES, ITEM_BY_ABILITY, UPGRADE_BY_RESEARCH_ABILITY
from phantom.config import BotConfig
from phantom.exporter import BotExporter
from phantom.knowledge import Knowledge
from phantom.macro.main import MacroPlan
from phantom.observation import OrderTarget
from phantom.parameters import AgentParameters


@dataclass(frozen=True)
class OrderedStructure:
    type_id: UnitTypeId
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
        self.ordered_structures = dict[int, UnitTypeId]()
        self.ordered_by_target = dict[OrderTarget, tuple[int, UnitTypeId]]()
        self.pending = dict[int, UnitTypeId]()
        self.pending_upgrades = set[UpgradeId]()

        if os.path.isfile(self.bot_config.version_path):
            logger.info(f"Reading version from {self.bot_config.version_path}")
            with open(self.bot_config.version_path) as f:
                self.version = f.read()
        else:
            logger.warning(f"Version not found: {self.bot_config.version_path}")

        self.parameters = AgentParameters()
        try:
            self.parameters.load(self.bot_config.params_path)
        except Exception as error:
            logger.warning(f"{error=} while loading {self.bot_config.params_path}")

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

        # if self.bot_config.profile_path:
        #     logger.info("Creating profiler")
        #     self.profiler = cProfile.Profile()
        # self.profiler.enable()

        knowledge = Knowledge(self)
        self.agent = Agent(self, self.bot_config.build_order, self.parameters, knowledge)
        self.parameters.sample()

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

        # await self.client.save_replay("tmp.SC2Replay")
        # cheat = Replay.from_file("tmp.SC2Replay")
        # cheat_state = cheat.steps[max(cheat.steps.keys())]
        # logger.debug(str(cheat_state.player_compositions()[2]))

        if self.bot_config.resign_after_iteration is not None and self.bot_config.resign_after_iteration < iteration:
            logger.info(f"Reached iteration {self.bot_config.resign_after_iteration}, resigning.")
            # await self.client.debug_kill_unit(self.structures)
            await self.client.leave()

        for error in self.state.action_errors:
            logger.warning(f"{error=}")

        if self.bot_config.debug_draw:
            for i, (t, plan) in enumerate(self.agent.macro.assigned_plans.items()):
                self._debug_draw_plan(self.unit_tag_dict.get(t), plan, index=i)

        if self.bot_config.profile_path:
            self.profiler.enable()

        for action in self.state.actions_unit_commands:
            for tag in action.unit_tags:
                self.handle_action(action, tag)

        for tag, ordered in list(self.ordered_structures.items()):
            if unit := self.unit_tag_dict.get(tag):
                ability = TRAIN_INFO[unit.type_id][ordered]["ability"]
                if not unit.is_using_ability(ability):
                    logger.warning(f"{unit=} is doing {unit.orders} and not as {ordered=}")
                    del self.ordered_structures[tag]
            else:
                logger.info(f"Trainer {tag=} is MIA for {ordered=}")
                del self.ordered_structures[tag]

        actions = await self.agent.step()
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

        while True:
            try:
                tag = self.replay_tag_queue.get(block=False)
                await self._send_replay_tag(tag)
            except Empty:
                break

    async def on_end(self, game_result: Result):
        await super().on_end(game_result)

        await self.client.save_replay(self.client.save_replay_path)

        if self.agent and self.bot_config.training:
            logger.info("Updating parameters...")
            if game_result == Result.Victory:
                self.parameters.update_distribution()
            self.parameters.save(self.bot_config.params_path)

    # async def on_before_start(self):
    #     await super().on_before_start()
    #
    async def on_building_construction_started(self, unit: Unit):
        logger.info(f"on_building_construction_started {unit=}")
        await super().on_building_construction_started(unit)
        self.ordered_structures.pop(unit.tag, None)
        self.pending[unit.tag] = unit.type_id

    async def on_building_construction_complete(self, unit: Unit):
        exists = unit.tag not in self._structures_previous_map
        logger.info(f"on_building_construction_complete {unit=}, {exists=}")
        await super().on_building_construction_complete(unit)

        if unit.type_id in {UnitTypeId.LAIR, UnitTypeId.HIVE} or unit.type_id in {UnitTypeId.CREEPTUMORBURROWED}:
            pass
        else:
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
        if unit := self._units_previous_map.get(unit_tag):
            for order in unit.orders:
                ability = order.ability.exact_id
                if item := UPGRADE_BY_RESEARCH_ABILITY.get(ability):
                    self.pending_upgrades.remove(item)
        else:
            logger.debug(f"{unit_tag=} vanished mysteriously")

    async def on_unit_created(self, unit: Unit):
        await super().on_unit_created(unit)

    async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId):
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
        await super().on_upgrade_complete(upgrade)
        self.pending_upgrades.discard(upgrade)

    def handle_action(self, action: ActionRawUnitCommand, tag: int) -> None:
        unit = self.unit_tag_dict.get(tag) or self._units_previous_map.get(tag)
        if not (item := ITEM_BY_ABILITY.get(action.exact_id)):
            return
        if item in {
            UnitTypeId.CREEPTUMORQUEEN,
            UnitTypeId.CREEPTUMOR,
            UnitTypeId.CHANGELING,
        }:
            return
        if unit and unit.type_id == UnitTypeId.EGG:
            # commands issued to a specific larva will be received by a random one
            # therefore, a direct lookup will often be incorrect
            # instead, all plans are checked for a match
            for t, p in self.agent.macro.assigned_plans.items():
                if item == p.item:
                    tag = t
                    break
        if plan := self.agent.macro.assigned_plans.get(tag):
            if item != plan.item:
                logger.info(f"{action=} for {item=} does not match {plan=}")
            else:
                del self.agent.macro.assigned_plans[tag]
                if isinstance(item, UpgradeId):
                    self.pending_upgrades.add(item)
                elif item in ALL_STRUCTURES and (
                    "requires_placement_position" in TRAIN_INFO[unit.type_id][item] or item == UnitTypeId.EXTRACTOR
                ):
                    if tag in self.unit_tag_dict:
                        self.ordered_structures[tag] = item
                else:
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
        eta: float = 0.0,
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

        text = f"{plan.item.name} {eta:.2f}"

        for position in positions:
            self.client.debug_text_world(text, position, color=font_color, size=font_size)

        if len(positions) == 2:
            position_from, position_to = positions
            position_from += Point3((0.0, 0.0, 0.1))
            position_to += Point3((0.0, 0.0, 0.1))
            self.client.debug_line_out(position_from, position_to, color=font_color)

        self.client.debug_text_screen(f"{1 + index} {round(eta or 0, 1)} {plan.item.name}", (0.01, 0.1 + 0.01 * index))

    async def _send_replay_tag(self, replay_tag: str) -> None:
        if replay_tag in self.replay_tags:
            return
        logger.info(f"Adding {replay_tag=}")
        self.replay_tags.add(replay_tag)
        await self.client.chat_send(f"Tag:{replay_tag}", True)
