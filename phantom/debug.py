import cProfile
import lzma
import os
import pickle
import pstats

from loguru import logger
from sc2.position import Point2, Point3
from sc2.unit import Unit

from phantom import PhantomBot

# from bot.ai.replay import load_replays
from phantom.macro.state import MacroPlan


class PhantomBotDebug(PhantomBot):
    profiler = cProfile.Profile()
    profile_path = "resources/profiling.prof"
    resign_after_iteration: int | None = None

    async def on_start(self) -> None:
        await super().on_start()
        logger.debug("Starting in debug mode")
        # dataset = list(load_replays("resources/games/*.pkl.xz"))
        # for x, y in tqdm(dataset):
        #     self.bot.ai.train_one(x, y)
        output_path = f"resources/maps/{self.game_info.map_name}.xz"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with lzma.open(output_path, "wb") as f:
            pickle.dump(self.game_info, f)
        # await self.bot.client.debug_upgrade()
        # num_points = 20
        # for _ in range(1_000_000):
        #     if num_points <= 0:
        #         break
        #     p = Point2(uniform(low=[0.0, 0.0], high=self.bot.game_info.map_size, size=2)).rounded
        #     if not self.bot.in_pathing_grid(p):
        #         continue
        #     await self.bot.client.debug_create_unit(
        #         [
        #             [UnitTypeId.ROACH, 1, p, 2],
        #             [UnitTypeId.ROACH, 1, p, 1],
        #         ]
        #     )
        #     num_points -= 1
        # await self.client.debug_create_unit(
        #     [
        #         [UnitTypeId.RAVAGER, 5, self.game_info.map_center, 1],
        #         [UnitTypeId.RAVAGER, 5, self.game_info.map_center, 2],
        #         [UnitTypeId.OVERSEER, 1, self.game_info.map_center, 1],
        #         [UnitTypeId.OVERSEER, 1, self.game_info.map_center, 2],
        #     ]
        # )
        # await self.bot.client.debug_create_unit(
        #     [
        #         [UnitTypeId.QUEEN, 3, self.bot.game_info.player_start_location, 1],
        #     ]
        # )

    async def on_step(self, iteration: int) -> None:
        # await self.client.debug_kill_unit(self.townhalls)

        if self.resign_after_iteration is not None:
            if self.resign_after_iteration < iteration:
                await self.client.leave()

        for error in self.state.action_errors:
            logger.debug(f"{error=}")

        self.profiler.enable()
        await super().on_step(iteration)
        self.profiler.disable()

        if self.actual_iteration % 100 == 0:
            logger.info("dump profiling")
            stats = pstats.Stats(self.profiler)
            stats = stats.strip_dirs().sort_stats(pstats.SortKey.CUMULATIVE)
            stats.dump_stats(filename=self.profile_path)
        for i, (t, plan) in enumerate(self.agent.macro.assigned_plans.items()):
            self._debug_draw_plan(self.unit_tag_dict.get(t), plan, index=i)

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
