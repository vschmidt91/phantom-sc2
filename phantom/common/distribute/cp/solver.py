import cvxpy as cp
import numpy as np
from loguru import logger

type Point = tuple[int, int]


class CvxPySolver:
    def __init__(self, n: int, m: int, include_total: bool = True) -> None:
        logger.info(f"Compiling cvxpy problem with {n=}, {m=}, {include_total=}")
        self.n = n
        self.m = m
        self.include_total = include_total

        self.variable = cp.Variable((n, m), nonneg=True)
        self.cost_param = cp.Parameter((n, m))
        self.limit_param = cp.Parameter(m, nonneg=True)

        constraints = [
            self.variable <= 1.0,
            cp.sum(self.variable, axis=1) == 1.0,
            cp.sum(self.variable, axis=0) <= self.limit_param,
        ]

        self.total_coeff_param = None
        self.total_limit_param = None
        if include_total:
            self.total_coeff_param = cp.Parameter(m)
            self.total_limit_param = cp.Parameter()
            constraints.append(
                cp.sum(cp.multiply(self.variable, cp.reshape(self.total_coeff_param, (1, m), order="C")))
                == self.total_limit_param
            )

        objective = cp.Minimize(cp.sum(cp.multiply(self.cost_param, self.variable)))
        self.problem = cp.Problem(objective, constraints)

        self.cost_param.value = np.zeros((n, m), dtype=float)
        self.limit_param.value = np.ones(m, dtype=float)
        if include_total:
            self.set_total(np.zeros(m), 0)

    def set_total(self, coeffs: np.ndarray, limit: int) -> None:
        if not self.include_total or self.total_coeff_param is None or self.total_limit_param is None:
            return
        coeffs = np.pad(coeffs, (0, self.m - coeffs.shape[0]), mode="constant", constant_values=0.0)
        self.total_coeff_param.value = coeffs
        self.total_limit_param.value = float(limit)

    def solve(self, cost: np.ndarray, limit: np.ndarray) -> np.ndarray:
        n, m = cost.shape
        padding = (0, self.n - n), (0, self.m - m)
        cost = np.pad(cost, padding, mode="constant", constant_values=np.inf)
        cost[n:, m:] = 0.0
        limit = np.pad(limit, (0, self.m - limit.shape[0]), mode="constant", constant_values=n)

        finite = np.isfinite(cost)
        if finite.any():
            scale = max(float(np.max(np.abs(cost[finite]))), 1.0)
        else:
            scale = 1.0
        penalty = max(scale * 1e6, 1e6)
        safe_cost = np.where(finite, cost, penalty)

        self.cost_param.value = safe_cost
        self.limit_param.value = limit

        self.problem.solve(warm_start=True)
        if self.variable.value is None:
            logger.warning(f"CVXPY assignment solve failed with status={self.problem.status!r}")
            return np.zeros((n, m), dtype=float)

        return self.variable.value[:n, :m]


_PROBLEM_CACHE = dict[Point, CvxPySolver]()


def get_cp_solver(n: int, m: int) -> CvxPySolver:
    key = n, m
    if not (problem := _PROBLEM_CACHE.get(key)):
        if n > 100 or m > 100:
            logger.warning(f"Compiling a large assignment problem with resolution {n}x{m}")
        _PROBLEM_CACHE[key] = (problem := CvxPySolver(*key))
    return problem
