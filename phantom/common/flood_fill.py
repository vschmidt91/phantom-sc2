from __future__ import annotations

from collections import deque
from collections.abc import Sequence

import numpy as np

from phantom.common.point import Point


def flood_fill_mask(mask: np.ndarray, seeds: Sequence[Point]) -> np.ndarray:
    """Return a boolean grid of all mask-connected tiles reachable from seeds.

    mask is expected to be indexed as [x, y].
    """
    if not any(seeds):
        return np.zeros_like(mask, dtype=bool)

    filled = np.zeros_like(mask, dtype=bool)
    queue: deque[Point] = deque()
    max_x, max_y = mask.shape

    for x, y in seeds:
        if 0 <= x < max_x and 0 <= y < max_y and mask[x, y] and not filled[x, y]:
            filled[x, y] = True
            queue.append((x, y))

    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < max_x and 0 <= ny < max_y and mask[nx, ny] and not filled[nx, ny]:
                filled[nx, ny] = True
                queue.append((nx, ny))

    return filled
