from dataclasses import dataclass
from functools import cached_property, lru_cache
from typing import Iterator

from sc2.position import Point2


@dataclass(frozen=True)
class HarvesterAssignment:
    items: dict[int, Point2]

    @property
    def count(self) -> int:
        return len(self.items)

    @cached_property
    def target(self) -> set[Point2]:
        return set(self.items.values())

    @lru_cache(maxsize=None)
    def assigned_to(self, p: Point2) -> frozenset[int]:
        return frozenset({u for u, t in frozenset(self.items.items()) if t == p})

    @lru_cache(maxsize=None)
    def assigned_to_set(self, ps: frozenset[Point2]) -> frozenset[int]:
        return frozenset({u for u, t in self.items.items() if t in ps})

    def assign(self, other: dict[int, Point2]) -> "HarvesterAssignment":
        return HarvesterAssignment({**self.items, **other})

    def unassign(self, other: set[int]) -> "HarvesterAssignment":
        return HarvesterAssignment({k: v for k, v in self.items.items() if k not in other})

    def __iter__(self) -> Iterator[int]:
        return iter(self.items)

    def __contains__(self, other: int) -> bool:
        return other in self.items

    @cached_property
    def _hash_value(self) -> int:
        return hash(frozenset(self.items.items()))

    def __hash__(self) -> int:
        return self._hash_value