import importlib
import math
import time
from dataclasses import dataclass
from functools import cached_property, cache
from typing import Callable, Collection, Generic, Hashable, Iterator, Mapping, TypeVar

import cvxpy as cp
import numpy as np
from cvxpy.problems.problem import SolverStats
from cvxpy.reductions import Solution
from loguru import logger

logger.info(f"{cp.installed_solvers()=}")

TKey = TypeVar("TKey", bound=Hashable)
TValue = TypeVar("TValue", bound=Hashable)


def cpg_solve(b, c, t, g, gw):

    n, m = c.shape

    log_n = max(3, math.ceil(math.log(max(n, m), 2)))
    N = 2 ** log_n

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

    # solve
    res = module.solve(upd, par)
    x = np.array(res.cpg_prim.x).reshape((N, N), order='F')[:n, :m]
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
        gw = np.full(len(b), 0.0)
        g = 0.0

        try:
            x_opt = cpg_solve(d, c, t, g, gw)
        except cp.error.SolverError as e:
            logger.error(f"Solver Error: {str(e)}")
            return Assignment({})

        # x_opt = problem.var_dict["x"].value
        indices = x_opt.argmax(axis=1)
        assignment = Assignment({ai: b[j] for (i, ai), j in zip(enumerate(a), indices) if 0 < x_opt[i, j]})

        return assignment
