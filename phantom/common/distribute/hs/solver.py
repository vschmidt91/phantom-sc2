from itertools import product

import highspy
import numpy as np
from loguru import logger

type Point = tuple[int, int]


class HighsPySolver:
    def __init__(self, n: int, m: int, include_total: bool = True) -> None:
        logger.info(f"Compiling highspy problem with {n=}, {m=}, {include_total=}")
        h = highspy.Highs()
        h.setOptionValue("presolve", "on")
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


_PROBLEM_CACHE = dict[Point, HighsPySolver]()


def get_hs_solver(n: int, m: int) -> HighsPySolver:
    key = n, m
    if not (problem := _PROBLEM_CACHE.get(key)):
        if n > 100 or m > 100:
            logger.warning(f"Compiling a large assignment problem with resolution {n}x{m}")
        _PROBLEM_CACHE[key] = (problem := HighsPySolver(*key))
    return problem
