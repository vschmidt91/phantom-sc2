import importlib
import math
from dataclasses import dataclass
from functools import cache, cached_property
from typing import Callable, Collection, Generic, Hashable, Iterator, Mapping, TypeVar

import cvxpy as cp
import numpy as np
from loguru import logger

logger.info(f"{cp.installed_solvers()=}")

TKey = TypeVar("TKey", bound=Hashable)
TValue = TypeVar("TValue", bound=Hashable)

SOLVER_OPTIONS = dict(
    solver="SCIPY",
    requires_grad=False,
    ignore_dpp=True,
    scipy_options=dict(
        time_limit=10e-3,
        presolve=False,
    ),
)


@cache
def harvester_assignment_problem(n, m):
    x = cp.Variable((n, m), "x")
    w = cp.Parameter((n, m), name="w")
    b = cp.Parameter(m, name="b")
    gw = cp.Parameter(m, name="gw")
    g = cp.Parameter(name="g")
    t = cp.Parameter(n, name="t")

    objective = cp.Minimize(cp.vdot(w, x))
    constraints = [
        cp.sum(x, 0) <= b,  # enforce even distribution
        cp.sum(x, 1) == t,
        cp.vdot(cp.sum(x, 0), gw) == g,
        0 <= x,
    ]
    problem = cp.Problem(objective, constraints)
    return problem


def cp_assign_harvesters(b, c, t, g, gw):
    n, m = c.shape
    problem = harvester_assignment_problem(n, m)
    problem.param_dict["w"].value = c
    problem.param_dict["t"].value = t
    problem.param_dict["b"].value = b
    problem.param_dict["g"].value = g
    problem.param_dict["gw"].value = gw
    problem.solve(**SOLVER_OPTIONS)
    x = problem.var_dict["x"].value
    if x is None:
        x = np.zeros((n, m))
    return x


@cache
def assignment_problem(n, m):
    x = cp.Variable((n, m), "x")
    w = cp.Parameter((n, m), name="w")
    b = cp.Parameter(m, name="b")
    t = cp.Parameter(n, name="t")

    objective = cp.Minimize(cp.vdot(w, x))
    constraints = [
        cp.sum(x, 0) <= b,  # enforce even distribution
        cp.sum(x, 1) == t,
        0 <= x,
    ]
    problem = cp.Problem(objective, constraints)
    return problem


def cp_assign(b, c, t):
    n, m = c.shape
    problem = assignment_problem(n, m)
    problem.param_dict["w"].value = c
    problem.param_dict["t"].value = t
    problem.param_dict["b"].value = b
    problem.solve(**SOLVER_OPTIONS)
    x = problem.var_dict["x"].value
    if x is None:
        x = np.zeros((n, m))
    return x


def cpg_solve(b, c, t, g, gw):
    n, m = c.shape

    log_n = max(4, math.ceil(math.log(max(n, m), 2)))
    N = 2**log_n

    prefix = f"assign{log_n}"
    module_name = f"{prefix}.cpg_module"
    module = importlib.import_module(module_name)

    par = getattr(module, f"{prefix}_cpg_params")()
    upd = getattr(module, f"{prefix}_cpg_updated")()

    for p in ["w", "b", "t", "g", "gw"]:
        try:
            setattr(upd, p, True)
        except AttributeError:
            raise AttributeError(f"{p} is not a parameter.")

    par.w = list(np.pad(c, ((0, N - c.shape[0]), (0, N - c.shape[1])), constant_values=1.0).flatten(order="F"))
    par.b = list(np.pad(b, (0, N - b.shape[0])).flatten(order="F"))
    par.t = list(np.pad(t, (0, N - t.shape[0])).flatten(order="F"))
    par.gw = list(np.pad(gw, (0, N - gw.shape[0])).flatten(order="F"))
    par.g = float(g)

    res = module.solve(upd, par)
    x = np.array(res.cpg_prim.x).reshape((N, N), order="F")[:n, :m]
    return x


@dataclass(frozen=True)
class Assignment(Generic[TKey, TValue], Mapping[TKey, TValue]):
    _items: dict[TKey, TValue]

    def assign(self, other: Mapping[TKey, TValue]) -> "Assignment":
        return Assignment({**self._items, **other})

    def unassign(self, other: Collection[TKey]) -> "Assignment":
        return Assignment({k: v for k, v in self._items.items() if k not in other})

    def __add__(self, other: Mapping[TKey, TValue]) -> "Assignment":
        return self.assign(other)

    def __sub__(self, other: Collection[TKey]) -> "Assignment":
        return self.unassign(other)

    @cached_property
    def _hash_value(self) -> int:
        return hash(frozenset(self.items()))

    def __hash__(self) -> int:
        return self._hash_value

    def __iter__(self) -> Iterator[TKey]:
        return iter(self._items)

    def __getitem__(self, __key):
        return self._items[__key]

    def __len__(self):
        return len(self._items)

    @classmethod
    def distribute(
        cls,
        a: list[TKey],
        b: list[TValue],
        cost_fn: Callable[[TKey, TValue], float] | np.ndarray,
        max_assigned: int | None = None,
        verbose=False,
    ) -> "Assignment[TKey, TValue]":
        if not a:
            return Assignment[TKey, TValue]({})
        if not b:
            return Assignment[TKey, TValue]({})

        if max_assigned is None:
            max_assigned = math.ceil(len(a) / len(b))

        d = np.full(len(b), max_assigned)
        c = (
            cost_fn
            if isinstance(cost_fn, np.ndarray)
            else np.array([[min(1e8, cost_fn(ai, bj)) for bj in b] for ai in a])
        )
        t = np.full(len(a), 1.0)

        try:
            x_opt = cp_assign(d, c, t)
        except cp.error.SolverError as e:
            logger.error(f"Solver Error: {str(e)}")
            return Assignment({})

        # x_opt = problem.var_dict["x"].value
        indices = x_opt.argmax(axis=1)
        assignment = Assignment({ai: b[j] for (i, ai), j in zip(enumerate(a), indices) if 0 < x_opt[i, j]})

        return assignment
