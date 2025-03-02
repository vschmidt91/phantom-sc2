import math
from dataclasses import dataclass
from functools import cached_property
from itertools import product
from typing import Callable, Collection, Generic, Hashable, Iterator, Mapping, TypeVar

import numpy as np
import scipy as sp
from loguru import logger
import cvxpy as cp

logger.info(f"{cp.installed_solvers()=}")

TKey = TypeVar("TKey", bound=Hashable)
TValue = TypeVar("TValue", bound=Hashable)


LINPROG_OPTIONS = {
    # "maxiter": 256,
    "time_limit": 5e-3,
}


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

        c = (
            cost_fn
            if isinstance(cost_fn, np.ndarray)
            else np.array([[min(1e8, cost_fn(ai, bj)) for bj in b] for ai in a])
        )

        x = cp.Variable((len(a), len(b)), 'x')
        w = cp.Parameter((len(a), len(b)), name='w')
        w.value = c

        constraints = [
            cp.sum(x, 0) <= max_assigned,  # enforce even distribution
            cp.sum(x, 1) == 1,
            0 <= x,
        ]
        problem = cp.Problem(cp.Minimize(cp.vdot(w, x)), constraints)
        problem.solve(solver="OSQP")
        x_opt = x.value


        # A_ub = sp.sparse.hstack([sp.sparse.identity(len(b))] * len(a))
        # b_ub = np.full(len(b), max_assigned)
        #
        # A_eq = sp.sparse.csr_matrix(np.repeat(np.identity(len(a)), len(b), axis=1))
        # b_eq = np.full(len(a), 1.0)
        #
        # c = (
        #     cost_fn.flatten()
        #     if isinstance(cost_fn, np.ndarray)
        #     else np.array([min(1e8, cost_fn(*p)) for p in product(a, b)])
        # )
        # res = linprog(
        #     c=c,
        #     A_ub=A_ub,
        #     b_ub=b_ub,
        #     A_eq=A_eq,
        #     b_eq=b_eq,
        #     method="highs",
        # )
        #
        # if res.x is None:
        #     logger.error(f"Target assigment failed: {res.message}")
        #     return Assignment({})
        #
        # x_opt = res.x.reshape((len(a), len(b)))


        indices = x_opt.argmax(axis=1)
        assignment = Assignment({ai: b[j] for (i, ai), j in zip(enumerate(a), indices) if 0 < x_opt[i, j]})

        return assignment
