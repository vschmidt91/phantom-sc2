from typing import Generic, Iterable, Iterator, TypeVar

from sc2.position import Point2

from ..utils import center
from .base import ResourceBase

T = TypeVar("T", bound=ResourceBase)


class ResourceGroup(ResourceBase, Generic[T], Iterable[T]):
    def __init__(self, items: Iterable[T], position: Point2 | None = None) -> None:
        self.items = list(items)
        super().__init__(position or center((r.position for r in self.items)))

    def __iter__(self) -> Iterator[T]:
        return iter(self.items)

    def __getitem__(self, index) -> T:
        return self.items[index]

    def __len__(self) -> int:
        return len(self.items)

    @property
    def remaining(self) -> int:
        return sum(r.remaining for r in self.items)

    @property
    def harvester_target(self) -> int:
        return sum(r.harvester_target for r in self.items)