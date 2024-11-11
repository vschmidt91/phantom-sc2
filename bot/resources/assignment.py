from dataclasses import dataclass
from functools import cached_property
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

    # @lru_cache(maxsize=None)
    def assigned_to(self, p: Point2) -> set[int]:
        return {u for u, t in self.items.items() if t == p}

    # @lru_cache(maxsize=None)
    def assigned_to_set(self, ps: set[Point2]) -> set[int]:
        return {u for u, t in self.items.items() if t in ps}

    def assign(self, other: dict[int, Point2]) -> "HarvesterAssignment":
        return HarvesterAssignment({**self.items, **other})

    def unassign(self, other: set[int]) -> "HarvesterAssignment":
        return HarvesterAssignment({k: v for k, v in self.items.items() if k not in other})

    def __iter__(self) -> Iterator[int]:
        return iter(self.items)

    def __contains__(self, other: int) -> bool:
        return other in self.items
