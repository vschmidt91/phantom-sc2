import math
from dataclasses import dataclass
from functools import cached_property
from itertools import product
from typing import Callable, Collection, Generic, Hashable, Iterator, Mapping, TypeVar

import numpy as np
from loguru import logger
from scipy.optimize import linprog

TKey = TypeVar("TKey", bound=Hashable)
TValue = TypeVar("TValue", bound=Hashable)


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
        cost_fn: Callable[[TKey, TValue], float],
        max_assigned: int | None = None,
        maxiter: int = 1_000,
    ) -> "Assignment[TKey, TValue]":

        if not a:
            return Assignment[TKey, TValue]({})
        if not b:
            return Assignment[TKey, TValue]({})

        pairs = list(product(a, b))

        if max_assigned is None:
            max_assigned = math.ceil(len(a) / len(b))

        opt = linprog(
            c=np.array([cost_fn(*p) for p in pairs]),
            # A_ub=np.array([[1.0 if bj == bk else 0.0 for ai, bj in pairs] for bk in b]),
            A_ub=np.tile(np.eye(len(b), len(b)), (1, len(a))),
            b_ub=np.full(len(b), max_assigned),
            # A_eq=np.array([[1.0 if ai == ak else 0.0 for ai, bj in pairs] for ak in a]),
            A_eq=np.repeat(np.eye(len(a), len(a)), len(b), axis=1),
            b_eq=np.full(len(a), 1.0),
            method="highs",
            bounds=(0.0, 1.0),
            options=dict(maxiter=maxiter),
            integrality=0,
        )

        if not opt.success:
            logger.error(f"Target assigment failed: {opt}")
            return Assignment({})

        result = Assignment({ai: bj for (ai, bj), wij in zip(pairs, opt.x) if wij > 0.5})

        return result
