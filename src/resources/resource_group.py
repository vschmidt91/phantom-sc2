
from __future__ import annotations
from enum import Enum
from typing import Iterator, Dict, Iterable, Set, List, Optional, TypeVar, Generic, Tuple, TYPE_CHECKING
from itertools import chain
import math
import logging

from sc2.unit import Unit
from sc2.position import Point2

from .resource_base import ResourceBase
from ..utils import center
if TYPE_CHECKING:
    from ..ai_base import AIBase

T = TypeVar('T', bound=ResourceBase)

class ResourceGroup(ResourceBase, Generic[T], Iterable[T]):

    def __init__(self, ai: AIBase, items: List[T], position: Optional[Point2] = None) -> None:
        if position == None:
            position = center((r.position for r in items))
        super().__init__(ai, position)
        self.items: List[T] = items

    def __iter__(self) -> Iterator[T]:
        return iter(self.items)

    def __getitem__(self, index) -> T:
        return self.items[index]

    def __len__(self) -> int:
        return len(self.items)

    @property
    def remaining(self) -> Iterable[int]:
        return sum(r.remaining for r in self.items)

    def flatten(self) -> Iterable[ResourceBase]:
        return (x for item in self.items for x in item.flatten())

    def update(self) -> None:
        for resource in self.items:
            resource.update()
        self.harvester_target = sum(r.harvester_target for r in self.items)