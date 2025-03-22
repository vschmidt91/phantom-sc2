import math
from dataclasses import dataclass
from functools import cache
from itertools import product
from typing import Hashable, TypeVar, Callable

import cvxpy as cp
import numpy as np
from scipy.optimize import linprog
from loguru import logger

from phantom.common.assignment import Assignment
from phantom.common.utils import CVXPY_OPTIONS, LINPROG_OPTIONS

TKey = TypeVar("TKey", bound=Hashable)
TValue = TypeVar("TValue", bound=Hashable)


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
        0 <= x,
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


def distribute(
    a: list[TKey],
    b: list[TValue],
    cost_fn: Callable[[TKey, TValue], float] | np.ndarray,
    max_assigned: list[int] | int | None = None,
    lp=False,
) -> "Assignment[TKey, TValue]":
    if not a:
        return Assignment[TKey, TValue]({})
    if not b:
        return Assignment[TKey, TValue]({})
    if max_assigned is None:
        max_assigned = math.ceil(len(a) / len(b))
    if isinstance(max_assigned, int):
        max_assigned = len(b) * [max_assigned]

    c = cost_fn if isinstance(cost_fn, np.ndarray) else np.array([[min(1e8, cost_fn(ai, bj)) for bj in b] for ai in a])
    d = np.array(max_assigned)

    try:
        if lp:
            opt = linprog(
                c=c.flatten(),
                A_ub=np.tile(np.eye(len(b), len(b)), (1, len(a))),
                b_ub=d,
                A_eq=np.repeat(np.eye(len(a), len(a)), len(b), axis=1),
                b_eq=np.full(len(a), 1.0),
                **LINPROG_OPTIONS,
            )
            if not opt.success:
                logger.error(f"Target assigment failed: {opt}")
                return Assignment({})
            x = opt.x.reshape(c.shape)
        else:
            x = cp_solve(c, d)
    except cp.error.SolverError as e:
        logger.error(f"Solver Error: {str(e)}")
        return Assignment({})

    indices = x.argmax(axis=1)
    assignment = Assignment({ai: b[j] for (i, ai), j in zip(enumerate(a), indices) if 0 < x[i, j]})

    return assignment
