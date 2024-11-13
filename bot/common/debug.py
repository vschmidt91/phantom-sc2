import cProfile
import pstats
from abc import ABC

from loguru import logger
from sc2.ids.unit_typeid import UnitTypeId

from bot.common.main import BotBase


class DebugBase(ABC):
    async def on_start(self) -> None:
        raise NotImplementedError()

    async def on_step_start(self) -> None:
        raise NotImplementedError()

    async def on_step_end(self) -> None:
        raise NotImplementedError()


class DebugDummy(DebugBase):
    pass


class Debug(DebugBase):
    bot: BotBase
    profiler = cProfile.Profile()

    async def on_start(self) -> None:
        await self.bot.client.debug_create_unit(
            [
                [UnitTypeId.ROACH, 10, self.bot.game_info.map_center, 1],
                [UnitTypeId.ROACH, 10, self.bot.game_info.map_center, 2],
            ]
        )

    async def on_step_start(self) -> None:
        for error in self.bot.state.action_errors:
            logger.info(f"{error=}")
        self.profiler.enable()

    async def on_step_end(self) -> None:
        self.profiler.disable()
        stats = pstats.Stats(self.profiler)
        if self.bot.actual_iteration % 100 == 0:
            logger.info("dump profiling")
            stats = stats.strip_dirs().sort_stats(pstats.SortKey.CUMULATIVE)
            stats.dump_stats(filename="profiling.prof")
