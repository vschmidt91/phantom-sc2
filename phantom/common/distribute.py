import math
from dataclasses import dataclass
from functools import cache
from typing import Hashable, TypeVar, Callable

import cvxpy as cp
import numpy as np
from loguru import logger

from phantom.common.assignment import Assignment
from phantom.common.utils import SOLVER_OPTIONS

TKey = TypeVar("TKey", bound=Hashable)
TValue = TypeVar("TValue", bound=Hashable)


@cache
def get_problem(n, m):
    x = cp.Variable((n, m), "x")
    c = cp.Parameter((n, m), name="c")

    spread_cost = 30 * cp.std(cp.sum(x, 0))
    assign_cost = cp.vdot(c, x)

    objective = cp.Minimize(assign_cost + spread_cost)
    constraints = [
        cp.sum(x, 1) == 1.0,
        0 <= x,
    ]
    problem = cp.Problem(objective, constraints)
    return problem


def cp_solve(c):
    n, m = c.shape
    problem = get_problem(n, m)
    problem.param_dict["c"].value = c
    problem.solve(**SOLVER_OPTIONS)
    solution = problem.var_dict["x"].value
    if solution is None:
        raise cp.SolverError()
    return solution


def distribute(
    a: list[TKey],
    b: list[TValue],
    cost_fn: Callable[[TKey, TValue], float] | np.ndarray,
) -> "Assignment[TKey, TValue]":
    if not a:
        return Assignment[TKey, TValue]({})
    if not b:
        return Assignment[TKey, TValue]({})

    c = cost_fn if isinstance(cost_fn, np.ndarray) else np.array([[min(1e8, cost_fn(ai, bj)) for bj in b] for ai in a])

    try:
        x = cp_solve(c)
    except cp.error.SolverError as e:
        logger.error(f"Solver Error: {str(e)}")
        return Assignment({})

    indices = x.argmax(axis=1)
    assignment = Assignment({ai: b[j] for (i, ai), j in zip(enumerate(a), indices) if 0 < x[i, j]})

    return assignment
