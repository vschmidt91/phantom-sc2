import importlib
import math
from dataclasses import dataclass
from functools import cache, cached_property
from typing import Callable, Collection, Generic, Hashable, Iterator, Mapping, TypeVar

import cvxpy as cp
import numpy as np
from loguru import logger

from phantom.common.utils import SOLVER_OPTIONS

logger.info(f"{cp.installed_solvers()=}")

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
