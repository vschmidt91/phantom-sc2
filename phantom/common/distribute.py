import math
from functools import cache
from itertools import product
from typing import Hashable, TypeVar

import cvxpy as cp
import numpy as np
from loguru import logger
from scipy.optimize import linprog

from phantom.cvxpygen.assign.assign import cpg_assign
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
    cost: np.ndarray,
    max_assigned: np.ndarray | int | None = None,
    lp=False,
) -> "Assignment[TKey, TValue]":
    if not a:
        return Assignment[TKey, TValue]({})
    if not b:
        return Assignment[TKey, TValue]({})
    if max_assigned is None:
        max_assigned = math.ceil(len(a) / len(b))
    if isinstance(max_assigned, int):
        max_assigned = np.full(len(b), max_assigned)

    try:
        if lp:

            x = cpg_assign(cost, max_assigned)
            if x is None:
                opt = linprog(
                    c=cost.flatten(),
                    A_ub=np.tile(np.identity(len(b)), (1, len(a))),
                    b_ub=max_assigned,
                    A_eq=np.repeat(np.identity(len(a)), len(b), axis=1),
                    b_eq=np.full(len(a), 1.0),
                    **LINPROG_OPTIONS,
                )
                if not opt.success:
                    logger.error(f"Target assigment failed: {opt}")
                    return Assignment({})
                x = opt.x.reshape(cost.shape)
        else:
            x = cp_solve(cost, max_assigned)
    except cp.error.SolverError as e:
        logger.error(f"Solver Error: {str(e)}")
        return Assignment({})

    indices = x.argmax(axis=1)
    assignment = Assignment({ai: b[j] for (i, ai), j in zip(enumerate(a), indices) if 0 < x[i, j]})

    return assignment
