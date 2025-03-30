import math
from collections.abc import Hashable
from functools import cache
from itertools import product
from typing import TypeVar

import cvxpy as cp
import highspy
import numpy as np
from loguru import logger

from phantom.common.utils import CVXPY_OPTIONS

TKey = TypeVar("TKey", bound=Hashable)
TValue = TypeVar("TValue", bound=Hashable)


class HighsPyProblem:
    def __init__(self, n: int, m: int) -> None:
        logger.debug(f"Creating HighsPyProblem with {n=}, {m=}")

        h = highspy.Highs()
        h.setOptionValue("presolve", "off")
        h.setOptionValue("log_to_console", "off")

        vs = {(i, j): h.addVariable(lb=0.0, ub=1.0) for i, j in product(range(n), range(m))}
        for i in range(n):
            h.addConstr(sum(vs[i, j] for j in range(m)) == 1.0)
        for j in range(m):
            h.addConstr(sum(vs[i, j] for i in range(n)) <= 1.0)
        h.minimize(sum(vs[i, j] for i in range(n) for j in range(m)))

        self.n = n
        self.m = m
        self.highspy = h
        self.lp = h.getLp()

    def solve(self, cost: np.ndarray, limit: np.ndarray) -> np.ndarray:
        self.lp.col_cost_ = cost.flatten()
        self.lp.row_upper_ = np.concatenate((np.ones(self.n), limit))
        self.highspy.passModel(self.lp)
        self.highspy.run()
        solution_flat = list(self.highspy.getSolution().col_value)
        solution = np.asarray(solution_flat).reshape((self.n, self.m))
        return solution


@cache
def get_highspy_problem(n, m):
    return HighsPyProblem(n, m)


@cache
def get_problem(n, m):
    x = cp.Variable((n, m), "x")
    c = cp.Parameter((n, m), name="c")
    b = cp.Parameter(m, name="b")

    assign_cost = cp.vdot(c, x)
    cost_overassign = 1e3 * cp.max(cp.sum(x, 0) - b)
    objective = cp.Minimize(assign_cost + cost_overassign)
    # spread_cost = 100 * cp.var(cp.sum(x, 0))
    # objective = cp.Minimize(assign_cost + spread_cost)

    constraints = [
        cp.sum(x, 1) == 1.0,
        # cp.sum(x, 0) == b,
        x >= 0,
    ]
    problem = cp.Problem(objective, constraints)
    return problem


def cp_solve(c, b):
    n, m = c.shape
    problem = get_problem(n, m)
    problem.param_dict["c"].value = c
    problem.param_dict["b"].value = b
    problem.solve(**CVXPY_OPTIONS)
    solution = problem.var_dict["x"].value
    if solution is None:
        raise cp.SolverError()
    return solution


@cache
def linprog_matrices(n: int, m: int) -> dict:
    return dict(
        A_ub=np.tile(np.identity(m), (1, n)),
        A_eq=np.repeat(np.identity(n), m, axis=1),
    )


def distribute(
    a: list[TKey],
    b: list[TValue],
    cost: np.ndarray,
    max_assigned: np.ndarray | int | None = None,
) -> dict[TKey, TValue]:
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

    problem = get_highspy_problem(n, m)
    x = problem.solve(cost, max_assigned)
    indices = x.argmax(axis=1)
    assignment = {ai: b[j] for (i, ai), j in zip(enumerate(a), indices, strict=False) if x[i, j] > 0}

    return assignment
