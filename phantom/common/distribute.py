import math
from collections.abc import Hashable, Mapping, Sequence
from functools import cache
from itertools import product
from typing import TypeVar

import highspy
import numpy as np
from loguru import logger
from scipy.optimize import linear_sum_assignment

type Point = tuple[int, int]

TKey = TypeVar("TKey", bound=Hashable)
TValue = TypeVar("TValue", bound=Hashable)
PROBLEM_RESOLUTION = 4


class HighsPySolver:
    def __init__(self, n: int, m: int, include_total=True) -> None:
        logger.info(f"Compiling highspy problem with {n=}, {m=}, {include_total=}")
        h = highspy.Highs()
        h.setOptionValue("presolve", "off")
        h.setOptionValue("parallel", "off")
        h.setOptionValue("log_to_console", False)

        vs = {(i, j): h.addVariable(lb=0.0, ub=1.0) for i, j in product(range(n), range(m))}
        for i in range(n):
            h.addConstr(sum(vs[i, j] for j in range(m)) == 1.0)
        for j in range(m):
            h.addConstr(sum(vs[i, j] for i in range(n)) <= 1.0)
        if include_total:
            h.addConstr(sum(vs[i, j] for i in range(n) for j in range(m)) == 1.0)
        h.minimize(sum(vs[i, j] for i in range(n) for j in range(m)))

        self.n = n
        self.m = m
        self.include_total = include_total
        self.highspy = h
        self.lp = h.getLp()

        self.cost = [0.0] * (self.n * self.m)
        self.row_lower = [1.0] * self.n + [0.0] * self.m
        self.row_upper = [1.0] * self.n + [0.0] * self.m

        if include_total:
            self.row_lower.append(0.0)
            self.row_upper.append(0.0)
            self.a_values = [1.0] * (3 * self.n * self.m)
            self.set_total(np.zeros(self.m), 0)

    def set_total(self, coeffs: np.ndarray, limit: int) -> None:
        coeffs = np.pad(coeffs, (0, self.m - coeffs.shape[0]), mode="constant", constant_values=0.0)
        self.a_values[2::3] = np.tile(coeffs, self.n)
        self.lp.a_matrix_.value_ = self.a_values
        self.row_lower[-1] = limit
        self.row_upper[-1] = limit

    def solve(self, cost: np.ndarray, limit: np.ndarray) -> np.ndarray:
        n, m = cost.shape
        padding = (0, self.n - n), (0, self.m - m)
        cost = np.pad(cost, padding, mode="constant", constant_values=np.inf)
        cost[n:, m:] = 0.0
        limit = np.pad(limit, (0, self.m - limit.shape[0]), mode="constant", constant_values=n)

        self.cost[:] = cost.flat
        if self.include_total:
            self.row_upper[self.n : -1] = limit
        else:
            self.row_upper[self.n :] = limit

        self.lp.col_cost_ = self.cost
        self.lp.row_lower_ = self.row_lower
        self.lp.row_upper_ = self.row_upper

        self.highspy.passModel(self.lp)
        self.highspy.run()

        result = self.highspy.getSolution()
        solution = np.reshape(result.col_value, (self.n, self.m))

        return solution[:n, :m]


@cache
def _get_assignment_solver(n: int, m: int) -> HighsPySolver:
    return HighsPySolver(n, m)


def get_assignment_solver(n: int, m: int) -> HighsPySolver:
    n2 = math.ceil(n / PROBLEM_RESOLUTION) * PROBLEM_RESOLUTION
    if n < n2:
        m += 1  # source padding also requires target padding
    m2 = math.ceil(m / PROBLEM_RESOLUTION) * PROBLEM_RESOLUTION
    return _get_assignment_solver(n2, m2)


def balanced_assignment(cost, k):
    C = np.nan_to_num(np.asarray(cost), posinf=1e10)
    N, M = C.shape
    caps = np.asarray(k, dtype=int).reshape(M)
    Cexp = np.repeat(C, caps, axis=1)
    r, c = linear_sum_assignment(Cexp)
    bounds = np.cumsum(caps)
    tgt = np.searchsorted(bounds, c, side="right")
    return dict(zip(r, tgt, strict=False))


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

    # solver = get_assignment_solver(n, m)
    # solver.set_total(np.zeros(m), 0)
    # x = solver.solve(cost, max_assigned)
    # indices = x.argmax(axis=1)
    # assignment = {ai: b[j] for (i, ai), j in zip(enumerate(a), indices, strict=False) if cost[i, j] < np.inf}

    ass = balanced_assignment(cost, max_assigned)
    assignment = {a[i]: b[j] for i, j in ass.items()}

    return assignment
