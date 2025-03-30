import cProfile
import json
import lzma
import os
import pickle
import pstats
from queue import Empty, Queue
from typing import Iterable

from loguru import logger
from sc2.data import Race, Result
from sc2.position import Point2, Point3
from sc2.unit import Unit

from phantom.agent import Agent
from phantom.common.main import BotBase
from phantom.data.multivariate_normal import NormalParameters
from phantom.data.normal import NormalParameter
from phantom.data.state import DataState
from phantom.knowledge import Knowledge
from phantom.macro.state import MacroId, MacroPlan
from phantom.observation import Observation
from phantom.parameters import AgentParameters, AgentPrior


class PhantomBot(BotBase):
    replay_tags = set[str]()
    replay_tag_queue = Queue[str]()
    version: str | None = None
    profiler = cProfile.Profile()

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        if os.path.isfile(self.bot_config.version_path):
            logger.info(f"Reading version from {self.bot_config.version_path}")
            with open(self.bot_config.version_path) as f:
                self.version = f.read()
        else:
            logger.warning(f"Version not found: {self.bot_config.version_path}")

        # load data
        priors = AgentPrior.to_dict()
        prior_distribution = NormalParameters.from_independent(priors.values())
        self.data = DataState(prior_distribution, list(priors.keys()))
        if os.path.isfile(self.bot_config.params_path):
            logger.info(f"Reading parameters from {self.bot_config.params_path}")
            try:
                with lzma.open(self.bot_config.params_path, "rb") as f:
                    self.data = pickle.load(f)
            except Exception as error:
                logger.warning(error)
        else:
            logger.warning(f"Parameters not found: {self.bot_config.params_path}")

        # sample parameters
        self.parameter_values = self.data.parameters.sample() if self.bot_config.training else self.data.parameters.mean
        parameter_dict = dict(zip(self.data.parameter_names, self.parameter_values, strict=False))
        parameter_distributions = {k: NormalParameter(float(v), 0, 0) for k, v in parameter_dict.items()}
        parameters = AgentParameters.from_dict(parameter_distributions | priors)
        knowledge = Knowledge(self)
        self.agent = Agent(parameters, knowledge)

        if self.bot_config.profile_path:
            logger.info("Creating profiler")
            self.profiler = cProfile.Profile()

    def add_replay_tag(self, replay_tag: str) -> None:
        self.replay_tag_queue.put(replay_tag)

    def planned_by_type(self, item: MacroId) -> Iterable:
        return self.agent.macro.planned_by_type(item)

    async def on_start(self) -> None:
        logger.debug("Bot starting")
        await super().on_start()

        def handle_message(message):
            severity = message.record["level"]
            self.add_replay_tag(f"log_{severity.name.lower()}")

        logger.add(handle_message, level=self.bot_config.tag_log_level, enqueue=True)

        if self.version:
            self.add_replay_tag(f"version_{self.version}")

        if self.bot_config.save_game_info:
            logger.info(f"Saving game info to {self.bot_config.save_game_info}")
            output_path = f"{self.bot_config.save_game_info}/{self.game_info.map_name}.xz"
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with lzma.open(output_path, "wb") as f:
                pickle.dump(self.game_info, f)

    async def on_step(self, iteration: int):
        await super().on_step(iteration)

        # local only: skip first iteration like on the ladder
        if iteration == 0:
            return

        if self.bot_config.resign_after_iteration is not None:
            if self.bot_config.resign_after_iteration < iteration:
                logger.info(f"Reached iteration {self.bot_config.resign_after_iteration}, resigning.")
                await self.client.leave()

        for error in self.state.action_errors:
            logger.warning(f"{error=}")

        if self.bot_config.profile_path:
            self.profiler.enable()

        if not self.bot_config.debug_draw:
            for i, (t, plan) in enumerate(self.agent.macro.assigned_plans.items()):
                self._debug_draw_plan(self.unit_tag_dict.get(t), plan, index=i)

        async for action in self.agent.step(Observation(self)):
            if not await action.execute(self):
                self.add_replay_tag("action_failed")
                logger.error(f"Action failed: {action}")

        while True:
            try:
                tag = self.replay_tag_queue.get(block=False)
                await self._send_replay_tag(tag)
            except Empty:
                break

        if self.bot_config.profile_path:
            self.profiler.disable()
            if self.actual_iteration % 100 == 0:
                logger.info(f"Writing profiling to {self.bot_config.profile_path}")
                stats = pstats.Stats(self.profiler)
                stats = stats.strip_dirs().sort_stats(pstats.SortKey.CUMULATIVE)
                stats.dump_stats(filename=self.bot_config.profile_path)

    async def on_end(self, game_result: Result):
        await super().on_end(game_result)

        if self.agent and self.bot_config.training:
            logger.info("Updating parameters...")
            self.data.update(self.parameter_values, game_result)
            try:
                with lzma.open(self.bot_config.params_path, "wb") as f:
                    pickle.dump(self.data, f)
                with open(self.bot_config.params_json_path, "w") as f:
                    json.dump(self.data.to_json(), f, indent=4)
            except Exception as e:
                logger.error(e)

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
