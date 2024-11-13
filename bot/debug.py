import cProfile
import lzma
import os
import pickle
import pstats
from abc import ABC
from dataclasses import dataclass

from loguru import logger

from bot.common.main import BotBase


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
        output_path = os.path.join("resources", f"{self.bot.game_info.map_name}.xz")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with lzma.open(output_path, "wb") as f:
            pickle.dump(self.bot.game_info, f)
        # await self.client.debug_upgrade()
        # await self.bot.client.debug_create_unit(
        #     [
        #         [UnitTypeId.ROACH, 10, self.bot.start_location, 1],
        #         [UnitTypeId.ROACH, 10, self.bot.enemy_start_locations[0], 2],
        #     ]
        # )

    async def on_step_start(self) -> None:
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
