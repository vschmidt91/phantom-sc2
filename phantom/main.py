import cProfile
import io
import lzma
import os
import pickle
import pstats
from collections import Counter
from queue import Empty, Queue

from ares import AresBot
from loguru import logger
from sc2.data import Race, Result
from sc2.position import Point2, Point3
from sc2.unit import Unit

from phantom.agent import Agent
from phantom.config import BotConfig
from phantom.exporter import BotExporter
from phantom.knowledge import Knowledge
from phantom.macro.state import MacroPlan
from phantom.observation import Observation
from phantom.parameters import AgentParameters


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

        if self.bot_config.profile_path:
            logger.info("Creating profiler")
            self.profiler = cProfile.Profile()

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

        knowledge = Knowledge(self)
        self.agent = Agent(self.bot_config.build_order, self.parameters, knowledge)
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
            # await self.client.debug_create_unit([
            #     [UnitTypeId.ROACH, 3, self.game_info.map_center, 1],
            #     [UnitTypeId.SCV, 20, self.game_info.map_center, 2],
            # ])
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

        planned = Counter(p.item for p in self.agent.macro.enumerate_plans())
        observation = Observation(self, self.agent.knowledge, planned)
        async for action in self.agent.step(self, observation):
            # logger.debug(f"Executing {action=}")
            if not await action.execute(self):
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
    # async def on_building_construction_started(self, unit: Unit):
    #     await super().on_building_construction_started(unit)
    #
    # async def on_building_construction_complete(self, unit: Unit):
    #     await super().on_building_construction_complete(unit)
    #
    # async def on_enemy_unit_entered_vision(self, unit: Unit):
    #     await super().on_enemy_unit_entered_vision(unit)
    #
    # async def on_enemy_unit_left_vision(self, unit_tag: int):
    #     await super().on_enemy_unit_left_vision(unit_tag)
    #
    # async def on_unit_destroyed(self, unit_tag: int):
    #     await super().on_unit_destroyed(unit_tag)
    #
    # async def on_unit_created(self, unit: Unit):
    #     await super().on_unit_created(unit)
    #
    # async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId):
    #     await super().on_unit_type_changed(unit, previous_type)
    #
    # async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float):
    #     await super().on_unit_took_damage(unit, amount_damage_taken)
    #
    # async def on_upgrade_complete(self, upgrade: UpgradeId):
    #     await super().on_upgrade_complete(upgrade)

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
