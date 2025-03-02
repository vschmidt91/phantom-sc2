import math
from dataclasses import dataclass
from functools import cached_property, cache
from typing import Callable, Collection, Generic, Hashable, Iterator, Mapping, TypeVar

import cvxpy as cp
import numpy as np
from loguru import logger

logger.info(f"{cp.installed_solvers()=}")

TKey = TypeVar("TKey", bound=Hashable)
TValue = TypeVar("TValue", bound=Hashable)


LINPROG_OPTIONS = {
    "solver": "OSQP",
    # "eps_abs": 1e-2,
    "time_limit": 10e-3,
}


@cache
def get_assignment_problem(n: int, m: int) -> cp.Problem:

    x = cp.Variable((n, m), 'x')
    w = cp.Parameter((n, m), name='w')
    b = cp.Parameter(m, name='b')
    x.value = np.zeros((n, m))
    b.value = np.ones(m)
    w.value = np.ones((n, m))

    constraints = [
        cp.sum(x, 0) <= b,  # enforce even distribution
        cp.sum(x, 1) == 1,
        0 <= x,
    ]
    problem = cp.Problem(cp.Minimize(cp.vdot(w, x)), constraints)
    try:
        problem.solve(solver="OSQP", max_iter=1)
    except cp.error.SolverError:
        pass
    return problem



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

        problem = get_assignment_problem(len(a), len(b))
        problem.param_dict["b"].value = np.full(len(b), max_assigned)
        problem.param_dict["w"].value = (
            cost_fn
            if isinstance(cost_fn, np.ndarray)
            else np.array([[min(1e8, cost_fn(ai, bj)) for bj in b] for ai in a])
        )
        try:
            problem.solve(verbose=verbose, **LINPROG_OPTIONS)
        except cp.error.SolverError as e:
            logger.error(f"Solver Error: {str(e)}")
            return Assignment({})

        x_opt = problem.var_dict["x"].value
        indices = x_opt.argmax(axis=1)
        assignment = Assignment({ai: b[j] for (i, ai), j in zip(enumerate(a), indices) if 0 < x_opt[i, j]})

        return assignment
