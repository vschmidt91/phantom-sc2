import math
from collections.abc import Hashable
from functools import cache
from typing import TypeVar

import cvxpy as cp
import numpy as np
import scipy
from loguru import logger
from scipy.optimize import linprog

from phantom.common.utils import CVXPY_OPTIONS, LINPROG_OPTIONS
from phantom.compiled.assign.assign import cpg_assign

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
    lp=False,
) -> dict[TKey, TValue]:
    n = len(a)
    m = len(b)
    if not a:
        return {}
    if not b:
        return {}
    if max_assigned is None:
        max_assigned = math.ceil(len(a) / len(b))
    if isinstance(max_assigned, int):
        max_assigned = np.full(len(b), max_assigned)

    try:
        if lp:
            x_cpg = cpg_assign(cost, max_assigned)
            if x_cpg is not None:
                x = x_cpg
            else:
                opt = linprog(
                    c=cost.flatten(),
                    b_ub=max_assigned,
                    b_eq=np.full(len(a), 1.0),
                    **linprog_matrices(n, m),
                    **LINPROG_OPTIONS,
                )

                if opt.x is None:
                    logger.error(f"Target assigment failed: {opt}")
                    return {}
                x = opt.x.reshape(cost.shape)
        else:
            x = cp_solve(cost, max_assigned)
    except cp.error.SolverError as e:
        logger.error(f"Solver Error: {str(e)}")
        return {}

    indices = x.argmax(axis=1)
    assignment = {ai: b[j] for (i, ai), j in zip(enumerate(a), indices, strict=False) if x[i, j] > 0}

    return assignment
