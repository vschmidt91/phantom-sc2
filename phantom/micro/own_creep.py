from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

import numpy as np
from sc2.data import Race
from sc2.position import Point2
from sc2.unit import Unit

from phantom.common.flood_fill import flood_fill_mask
from phantom.common.point import Point, to_point
from phantom.common.utils import structure_perimeter

if TYPE_CHECKING:
    from phantom.main import PhantomBot


class OwnCreep:
    def __init__(self, bot: PhantomBot, update_interval: int = 16) -> None:
        self.bot = bot
        self.update_interval = max(1, update_interval)
        self.grid = np.zeros(bot.game_info.map_size, dtype=bool)
        self._targets: list[Point] | None = None

    def on_step(self) -> None:
        if self.bot.actual_iteration % self.update_interval == 0:
            self._update()

    def is_on_own_creep(self, p: Point | Point2 | Unit) -> bool:
        if isinstance(p, Unit):
            q = to_point(p.position)
        elif isinstance(p, Point2):
            q = to_point(p)
        else:
            q = p
        x, y = q
        if x < 0 or y < 0 or x >= self.grid.shape[0] or y >= self.grid.shape[1]:
            return False
        return bool(self.grid[x, y])

    @property
    def targets(self) -> list[Point]:
        if self._targets is None:
            xs, ys = np.where(self.grid)
            self._targets = list(zip(xs.tolist(), ys.tolist(), strict=False))
        return self._targets

    def _update(self) -> None:
        visibility_grid = np.equal(self.bot.state.visibility.data_numpy.T, 2.0)
        creep_grid = self.bot.mediator.get_creep_grid.T == 1
        visible_creep = creep_grid & visibility_grid

        if self.bot.enemy_race in {Race.Zerg, Race.Random}:
            self.grid = self._own_creep_zvz(visible_creep)
        else:
            self.grid = visible_creep

        self._targets = None

    def _own_creep_zvz(self, visible_creep: np.ndarray) -> np.ndarray:
        seeds: list[Point] = []
        for townhall in self.bot.townhalls.ready:
            seeds.extend(self._valid_seeds(structure_perimeter(townhall), visible_creep))

        if not seeds:
            return np.zeros_like(visible_creep, dtype=bool)

        return flood_fill_mask(visible_creep, seeds)

    def _valid_seeds(self, points: Iterable[Point], visible_creep: np.ndarray) -> list[Point]:
        max_x, max_y = visible_creep.shape
        seeds: list[Point] = []
        for x, y in points:
            if 0 <= x < max_x and 0 <= y < max_y and visible_creep[x, y]:
                seeds.append((x, y))
        return seeds
