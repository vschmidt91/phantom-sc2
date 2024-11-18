import cProfile
import lzma
import os
import pickle
import pstats
from abc import ABC
from dataclasses import dataclass

from loguru import logger
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2, Point3
from sc2.unit import Unit
from tqdm import tqdm

from bot.ai.replay import load_replays
from bot.common.main import BotBase
from bot.macro.planner import MacroPlan


class DebugBase(ABC):
    async def on_start(self) -> None:
        raise NotImplementedError()

    async def on_step_start(self) -> None:
        raise NotImplementedError()

    async def on_step_end(self) -> None:
        raise NotImplementedError()


@dataclass(frozen=True)
class DebugDummy(DebugBase):
    async def on_start(self) -> None:
        pass

    async def on_step_start(self) -> None:
        pass

    async def on_step_end(self) -> None:
        pass


@dataclass(frozen=True)
class Debug(DebugBase):
    bot: BotBase
    profiler = cProfile.Profile()

    async def on_start(self) -> None:
        logger.debug("Starting in debug mode")
        dataset = list(load_replays("resources/games/*.pkl.xz"))
        for x, y in tqdm(dataset):
            self.bot.ai.train_one(x, y)
        output_path = os.path.join("resources", "maps", f"{self.bot.game_info.map_name}.xz")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with lzma.open(output_path, "wb") as f:
            pickle.dump(self.bot.game_info, f)
        # await self.bot.debug_upgrade()
        await self.bot.client.debug_create_unit(
            [
                [UnitTypeId.OVERLORD, 10, self.bot.game_info.map_center, 1],
                [UnitTypeId.ROACH, 30, self.bot.game_info.map_center, 1],
                [UnitTypeId.ROACH, 30, self.bot.game_info.map_center, 2],
                [UnitTypeId.OVERLORD, 10, self.bot.game_info.map_center, 2],
            ]
        )

    async def on_step_start(self) -> None:
        # if self.bot.actual_iteration > 100:
        #     await self.bot.client.leave()
        for error in self.bot.state.action_errors:
            logger.debug(f"{error=}")
        self.profiler.enable()

    async def on_step_end(self) -> None:
        self.profiler.disable()
        stats = pstats.Stats(self.profiler)
        if self.bot.actual_iteration % 100 == 0:
            logger.info("dump profiling")
            stats = stats.strip_dirs().sort_stats(pstats.SortKey.CUMULATIVE)
            stats.dump_stats(filename="profiling.prof")
        for i, (t, plan) in enumerate(self.bot.planner._assigned_plans.items()):
            self._debug_draw_plan(self.bot.unit_tag_dict.get(t), plan, index=i)

        for i, (t, n) in enumerate(self.bot._predicted_enemy_composition.items()):
            self.bot.client.debug_text_screen(f"{i} {t}: {n}", (0.0, 0.3 + 0.01 * i))

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
            height = self.bot.get_terrain_z_height(plan.target)
            positions.append(Point3((plan.target.x, plan.target.y, height)))

        if unit:
            height = self.bot.get_terrain_z_height(unit)
            positions.append(Point3((unit.position.x, unit.position.y, height)))

        text = f"{plan.item.name} {eta:.2f}"

        for position in positions:
            self.bot.client.debug_text_world(text, position, color=font_color, size=font_size)

        if len(positions) == 2:
            position_from, position_to = positions
            position_from += Point3((0.0, 0.0, 0.1))
            position_to += Point3((0.0, 0.0, 0.1))
            self.bot.client.debug_line_out(position_from, position_to, color=font_color)

        self.bot.client.debug_text_screen(
            f"{1 + index} {round(eta or 0, 1)} {plan.item.name}", (0.01, 0.1 + 0.01 * index)
        )
