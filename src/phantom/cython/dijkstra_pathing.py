import math
from dataclasses import dataclass
from functools import cached_property

import numpy as np

from phantom.common.utils import Point
from phantom.cython.cy_dijkstra import cy_dijkstra  # type: ignore


@dataclass(frozen=True)
class DijkstraPathing:
    cost: np.ndarray
    targets: list[Point]

    @cached_property
    def _pathing(self):
        cost = self.cost.astype(np.float64)
        targets = np.array(self.targets).astype(np.intp)
        return cy_dijkstra(cost, targets)

    @cached_property
    def prev_x(self):
        return np.asarray(self._pathing.prev_x)

    @cached_property
    def prev_y(self):
        return np.asarray(self._pathing.prev_y)

    @cached_property
    def dist(self):
        return np.asarray(self._pathing.dist)

    def get_path(self, target: Point, limit: float = math.inf) -> list[Point]:
        path = list[Point]()
        x, y = target
        while len(path) < limit:
            path.append((x, y))
            x2 = self.prev_x[x, y]
            y2 = self.prev_y[x, y]
            if x2 < 0:
                break
            x, y = x2, y2
        return path
