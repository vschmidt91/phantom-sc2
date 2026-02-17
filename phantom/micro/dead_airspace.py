from collections.abc import Mapping
from typing import TYPE_CHECKING

import numpy as np
from scipy.ndimage import binary_dilation

from phantom.common.air_range import air_range_of
from phantom.common.point import to_point

if TYPE_CHECKING:
    from sc2.unit import Unit


class DeadAirspace:
    def __init__(self, pathing_grid: np.ndarray, min_range: int = 0, max_range: int = 20) -> None:
        self.min_range = min_range
        self.max_range = max_range
        self.candidate_ranges = list(range(min_range, max_range + 1))
        self.pathable_grid = np.asarray(pathing_grid, dtype=bool)
        self._shootable_grids = self._build_shootable_grids()

    def check(self, attacker: "Unit", target: "Unit") -> bool:
        if not attacker.can_attack_air:
            return False

        target_pos = to_point(target.position)
        if not self._is_in_bounds(target_pos):
            return False

        range_key = self._range_key(air_range_of(attacker))
        shootable_grid = self._shootable_grids.get(range_key)
        if shootable_grid is None:
            return False

        return bool(shootable_grid[target_pos])

    def _build_shootable_grids(self) -> Mapping[int, np.ndarray]:
        result = dict[int, np.ndarray]()
        for r in self.candidate_ranges:
            kernel = self._circular_kernel(r)
            result[r] = binary_dilation(self.pathable_grid, structure=kernel)
        return result

    def _range_key(self, air_range: float) -> int:
        rounded = int(np.floor(air_range + 1e-6))
        return min(max(rounded, self.min_range), self.max_range)

    def _is_in_bounds(self, point: tuple[int, int]) -> bool:
        return 0 <= point[0] < self.pathable_grid.shape[0] and 0 <= point[1] < self.pathable_grid.shape[1]

    @staticmethod
    def _circular_kernel(radius: int) -> np.ndarray:
        x = np.arange(-radius, radius + 1)
        y = np.arange(-radius, radius + 1)
        xx, yy = np.meshgrid(x, y, indexing="ij")
        return (xx**2 + yy**2) <= radius**2
