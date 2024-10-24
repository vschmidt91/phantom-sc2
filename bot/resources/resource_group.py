from typing import Generic, Iterable, Iterator, List, Optional, TypeVar

from sc2.position import Point2

from ..utils import center
from .resource_base import ResourceBase

T = TypeVar("T", bound=ResourceBase)


class ResourceGroup(ResourceBase, Generic[T], Iterable[T]):
    def __init__(self, items: List[T], position: Optional[Point2] = None) -> None:
        if position is None:
            position = center((r.position for r in items))
        super().__init__(position)
        self.items: List[T] = items

    def __iter__(self) -> Iterator[T]:
        return iter(self.items)

    def __getitem__(self, index) -> T:
        return self.items[index]

    def __len__(self) -> int:
        return len(self.items)

    def flatten(self) -> Iterable[T]:
        return (x for item in self.items for x in item.flatten())

    @property
    def remaining(self) -> int:
        return sum(r.remaining for r in self.items)

    @property
    def harvester_target(self) -> int:
        return sum(r.harvester_target for r in self.items)
