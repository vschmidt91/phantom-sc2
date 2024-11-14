from dataclasses import dataclass
from functools import cache, cached_property
from typing import Collection, Generic, Hashable, Iterator, Mapping, TypeVar

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
