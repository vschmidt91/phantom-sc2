
import numpy as np
import itertools
from scipy.signal import convolve2d, resample
from scipy.ndimage import zoom
from typing import Mapping, Dict, Tuple
import cv2

from sc2.position import Point2


def solve_poisson(boundary: np.ndarray, sources: Dict[Point2, float], x0: np.ndarray, omega: float) -> np.ndarray:

    print(boundary.shape)

    def get(v: np.ndarray, i: int, j: int, default: float):
        if i < 0 or boundary.shape[0] <= i:
            return default
        if j < 0 or boundary.shape[1] <= j:
            return default
        if boundary[i, j]:
            return default
        p = Point2((i, j))
        if p in sources:
            return sources[p]
        return v[i, j]

    x = x0.copy()

    for n in range(1024):

        r = 0.0
        
        for (i, j), v in np.ndenumerate(x):

            if boundary[i, j]:
                continue

            p = Point2((i, j))
            if p in sources:
                x[i, j] = sources[p]
                continue

            v2 = 0
            v2 += get(x, i - 1, j, v)
            v2 += get(x, i + 1, j, v)
            v2 += get(x, i, j - 1, v)
            v2 += get(x, i, j + 1, v)
            v2 /= 4

            r += abs(v2 - v)

            x[i, j] += omega * (v2 - v)

        r /= np.prod(x.shape)
        print(r)
        if r < 3e-5:
            break

    return x

def resize(array: np.ndarray, shape: Tuple[int, int]) -> np.ndarray:
    resized = cv2.resize(array, (shape[1], shape[0]), interpolation=cv2.INTER_LINEAR)
    return resized

def solve_poisson_full(boundary: np.ndarray, sources: Dict[Point2, float], omega: float):

    if any(d < 4 for d in boundary.shape):
        x0 = 0.5 * np.ones_like(boundary, dtype=np.float)
        x1 = solve_poisson(boundary, sources, x0, omega)
        return x1


    shape_half = (int(boundary.shape[0] / 2), int(boundary.shape[1] / 2))
    boundary_half = resize(boundary.astype(np.float), shape_half)
    boundary_half = 1 <= boundary_half
    sources_half = {
        (0.5 * p).rounded: v
        for p, v in sources.items()
    }

    xh = solve_poisson_full(boundary_half, sources_half, omega)
    x0 = xh
    x0 = resize(x0, boundary.shape)
    x = solve_poisson(boundary, sources, x0, omega)

    # x = (1 - boundary) * x + boundary
    # matplotlib.pyplot.imshow(x)

    return x