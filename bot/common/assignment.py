from dataclasses import dataclass
from functools import cache, cached_property
from typing import Callable, Collection, Generic, Hashable, Iterator, Mapping, TypeVar

import numpy as np
from loguru import logger
from scipy.optimize import LinearConstraint, milp

from bot.common.constants import IMPOSSIBLE_TASK_COST

TKey = TypeVar("TKey", bound=Hashable)
TValue = TypeVar("TValue", bound=Hashable)


@dataclass(frozen=True)
class Assignment(Generic[TKey, TValue], Mapping[TKey, TValue]):

    _items: dict[TKey, TValue]

    @cache
    def assigned_to(self, p: TValue) -> frozenset[TKey]:
        return frozenset({u for u, t in self._items.items() if t == p})

    @cache
    def assigned_to_set(self, ps: Collection[TValue]) -> frozenset[TKey]:
        return frozenset({u for u, t in self._items.items() if t in ps})

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
    def optimize(
        cls, a: list[TKey], b: list[TValue], cost_fn: Callable[[TKey, TValue], float], max_duration_ms: int = 100
    ) -> "Assignment[TKey, TValue]":

        if not a:
            return Assignment[TKey, TValue]({})
        if not b:
            return Assignment[TKey, TValue]({})

        cost_array = np.array([[cost_fn(ai, bj) for ai in a] for bj in b])
        assignment_matches_unit = np.array([[1 if ai == u else 0 for ai in a for bj in b] for u in a])
        assignment_matches_target = np.array([[1 if bj == u else 0 for ai in a for bj in b] for u in b])
        min_assigned = len(a) // len(b)
        constraints = [
            LinearConstraint(
                assignment_matches_unit,
                np.ones([len(a)]),
                np.ones([len(a)]),
            ),
            LinearConstraint(
                assignment_matches_target,
                np.full([len(b)], min_assigned),
                np.full([len(b)], min_assigned + 1),
            ),
        ]
        options = dict(
            time_limit=max_duration_ms / 1000,
        )
        # bias = np.array([dither((a.tag, b.tag)) for a in self.units for b in self.enemy_units])
        opt = milp(
            c=cost_array.flat,
            constraints=constraints,
            options=options,
        )
        if not opt.success:
            logger.error(f"Target assigment failed: {opt}")
            return Assignment({})
        x_opt = opt.x.reshape((len(a), len(b)))
        target_indices = x_opt.argmax(axis=1)
        result = Assignment[TKey, TValue](
            {
                u: b[target_indices[i]]
                for i, u in enumerate(a)
                if cost_array[target_indices[i], i] < IMPOSSIBLE_TASK_COST
            }
        )
        return result
