import math
from collections.abc import Hashable, Mapping, Sequence
from typing import TypeVar

import numpy as np

from phantom.common.distribute.cpg.solver import get_cpg_solver
from phantom.common.distribute.hs.solver import get_hs_solver

type Point = tuple[int, int]

TKey = TypeVar("TKey", bound=Hashable)
TValue = TypeVar("TValue", bound=Hashable)

PROBLEM_RESOLUTION = 8
_MAX_CPG_SIZE = 128


def get_assignment_solver(n: int, m: int):
    cpg_solver = get_cpg_solver()
    if cpg_solver is not None and cpg_solver.can_solve(n, m, _MAX_CPG_SIZE):
        return cpg_solver

    n2 = math.ceil(n / PROBLEM_RESOLUTION) * PROBLEM_RESOLUTION
    if n < n2:
        m += 1
    m2 = math.ceil(m / PROBLEM_RESOLUTION) * PROBLEM_RESOLUTION
    return get_hs_solver(n2, m2)


def distribute[TKey: Hashable, TValue: Hashable](
    a: Sequence[TKey],
    b: Sequence[TValue],
    cost: np.ndarray,
    max_assigned: np.ndarray | int | None = None,
    sticky: Mapping[TKey, TValue] | None = None,
    sticky_cost: float = 0.0,
) -> Mapping[TKey, TValue]:
    cost = np.array(cost, copy=True)
    n = len(a)
    m = len(b)
    if n == 0:
        return {}
    if m == 0:
        return {}
    if max_assigned is None:
        max_assigned = math.ceil(n / m)
    if isinstance(max_assigned, int):
        max_assigned = np.full(m, float(max_assigned))
    if np.isnan(cost).any():
        raise ValueError("NaN values are not valid for assignment cost")

    if sticky:
        target_to_index = {bj: j for j, bj in enumerate(b)}
        for i, ai in enumerate(a):
            previous = sticky.get(ai)
            if previous is None:
                continue
            if (j := target_to_index.get(previous)) is not None:
                cost[i, j] = sticky_cost

    solver = get_assignment_solver(n, m)
    solver.set_total(np.zeros(m), 0)

    x = solver.solve(cost, max_assigned)
    indices = x.argmax(axis=1)
    return {ai: b[j] for (i, ai), j in zip(enumerate(a), indices, strict=False) if cost[i, j] < np.inf}
