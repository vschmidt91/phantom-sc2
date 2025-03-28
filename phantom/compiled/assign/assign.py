import importlib
import os
import pickle
import pkgutil
from dataclasses import dataclass
from functools import cached_property, cache

import cvxpy as cp
import numpy as np
from loguru import logger

BASE_DIR = os.path.dirname(__file__)


@dataclass(frozen=True)
class AssignSolver:
    module_path: str

    @cached_property
    def shape(self) -> tuple[int, int]:
        parts = self.module_path.split("_")
        return int(parts[1]), int(parts[2])

    @cached_property
    def size(self) -> int:
        return self.shape[0] * self.shape[1]

    @cached_property
    def problem(self) -> cp.Problem:
        with open(os.path.join(BASE_DIR, self.module_path, "problem.pickle"), "rb") as f:
            return pickle.load(f)

    @cached_property
    def module(self):
        return importlib.import_module(f"phantom.cvxpygen.assign.{self.module_path}.cpg_solver")

    @cached_property
    def solver(self):
        return getattr(self.module, "cpg_solve")

    def can_solve(self, shape) -> bool:
        return all(a <= b for a, b in zip(shape, self.shape))

    def solve(self, cost: np.ndarray, limit: np.ndarray) -> np.ndarray:
        cost_param = self.problem.param_dict["w"]
        cost_padded = np.zeros_like(cost_param.value)
        cost_padded[: cost.shape[0], : cost.shape[1]] = cost
        cost_param.value = cost_padded

        limit_param = self.problem.param_dict["b"]
        limit_padded = np.zeros_like(limit_param.value)
        limit_padded[: limit.shape[0]] = limit
        limit_param.value = limit_padded

        self.solver(self.problem)

        solution_var = self.problem.var_dict["x"]
        solution_padded = solution_var.value
        solution = solution_padded[: cost.shape[0], : cost.shape[1]]

        return solution


@cache
def load_solvers() -> list[AssignSolver]:
    modules = list(pkgutil.iter_modules([BASE_DIR]))
    solver_modules = [m.name for m in modules if m.ispkg]
    solvers = [AssignSolver(f) for f in solver_modules]
    logger.info(f"{solvers=}")
    return solvers


def cpg_assign(cost: np.ndarray, limit: np.ndarray) -> np.ndarray | None:
    assert cost.ndim == 2
    assert limit.ndim == 1
    assert limit.shape[0] == cost.shape[1]

    solvers = [s for s in load_solvers() if s.can_solve(cost.shape)]
    if solver := min(solvers, key=lambda s: s.size, default=None):
        return solver.solve(cost, limit)

    return None
