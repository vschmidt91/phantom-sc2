import math
from collections.abc import Hashable, Mapping, Sequence
from itertools import product
from typing import TypeVar

import highspy
import numpy as np
from loguru import logger

TKey = TypeVar("TKey", bound=Hashable)
TValue = TypeVar("TValue", bound=Hashable)


class HighsPyProblem:
    def __init__(self, n: int, m: int, include_total: bool) -> None:
        logger.debug(f"Compiling highspy problem with {n=}, {m=}, {include_total=}")
        h = highspy.Highs()
        # h.setOptionValue("time_limit", 0.1)
        h.setOptionValue("presolve", "off")
        # h.setOptionValue("simplex_iteration_limit", 64)
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

    def set_total(self, coeffs: np.ndarray, limit: int) -> None:
        self.a_values[2::3] = np.tile(coeffs, self.n)
        self.lp.a_matrix_.value_ = self.a_values
        self.row_lower[-1] = limit
        self.row_upper[-1] = limit

    def solve(self, cost: np.ndarray, limit: np.ndarray) -> np.ndarray:
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
        return np.reshape(self.highspy.getSolution().col_value, (self.n, self.m))


_PROBLEM_CACHE = dict[tuple[int, int, bool], HighsPyProblem]()


def _get_problem(n: int, m: int, t: bool) -> HighsPyProblem:
    if not (problem := _PROBLEM_CACHE.get((n, m, t))):
        _PROBLEM_CACHE[n, m, t] = (problem := HighsPyProblem(n, m, t))
    return problem


def distribute(
    a: Sequence[TKey],
    b: Sequence[TValue],
    cost: np.ndarray,
    max_assigned: np.ndarray | int | None = None,
) -> Mapping[TKey, TValue]:
    n = len(a)
    m = len(b)
    if n == 0:
        return {}
    if m == 0:
        return {}
    if max_assigned is None:
        max_assigned = math.ceil(n / m)
    if isinstance(max_assigned, int):
        max_assigned = np.full(m, max_assigned)

    problem = _get_problem(n, m, False)
    x = problem.solve(cost, max_assigned)
    indices = x.argmax(axis=1)
    assignment = {ai: b[j] for (i, ai), j in zip(enumerate(a), indices, strict=False) if x[i, j] > 0}

    return assignment
