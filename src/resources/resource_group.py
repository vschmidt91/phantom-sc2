from __future__ import annotations

from typing import Generic, Iterable, Iterator, List, Optional, TypeVar, TYPE_CHECKING

from sc2.position import Point2

if TYPE_CHECKING:
    from src.ai_base import AIBase

from ..utils import center
from .resource_base import ResourceBase

T = TypeVar("T", bound=ResourceBase)


class ResourceGroup(ResourceBase, Generic[T], Iterable[T]):
    def __init__(
        self, ai: AIBase, items: List[T], position: Optional[Point2] = None
    ) -> None:
        if position is None:
            position = center((r.position for r in items))
        super().__init__(ai, position)
        self.items: List[T] = items

    def __iter__(self) -> Iterator[T]:
        return iter(self.items)

    def __getitem__(self, index) -> T:
        return self.items[index]

    def __len__(self) -> int:
        return len(self.items)

    def flatten(self) -> Iterable[T]:
        return (x for item in self.items for x in item.flatten())

    async def on_step(self) -> None:
        for item in self.items:
            await item.on_step()
        await super().on_step()

    @property
    def remaining(self) -> Iterable[int]:
        return sum(r.remaining for r in self.items)

    @property
    def harvester_target(self) -> int:
        return sum(r.harvester_target for r in self.items)
