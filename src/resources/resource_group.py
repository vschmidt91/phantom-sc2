
from __future__ import annotations
from enum import Enum
from typing import Iterator, Dict, Iterable, Set, List, Optional, TypeVar, Generic, Tuple, TYPE_CHECKING
from itertools import chain
import math

from google.protobuf.descriptor import Error

from sc2.unit import Unit
from sc2.position import Point2

from .resource_base import ResourceBase
from ..utils import center
if TYPE_CHECKING:
    from ..ai_base import AIBase

T = TypeVar('T', bound=ResourceBase)

class BalancingMode(Enum):
    NONE = 0
    MINIMIZE_TRANSFERS = 1
    EVEN_DISTRIBUTION = 2

class ResourceGroup(ResourceBase, Generic[T], Iterable[T]):

    def __init__(self, ai: AIBase, items: List[T], position: Optional[Point2] = None) -> None:
        if position == None:
            position = center((r.position for r in items))
        super().__init__(ai, position)
        self.items: List[T] = items
        self.balancing_mode: BalancingMode = BalancingMode.MINIMIZE_TRANSFERS
        self.vespene_switching_enabled: bool = False

    def __iter__(self) -> Iterator[T]:
        return iter(self.items)

    def __getitem__(self, index) -> T:
        return self.items[index]

    def __len__(self) -> int:
        return len(self.items)

    def get_resource(self, harvester: int) -> Optional[ResourceBase]:
        resource, item = self.get_resource_and_item(harvester)
        return resource

    def get_resource_and_item(self, harvester: int) -> Optional[Tuple[ResourceBase, T]]:
        for item in self.items:
            result = item.get_resource(harvester)
            if result:
                return result, item
        return None, None

    def try_add(self, harvester: int) -> bool:
        resource = None
        if self.balancing_mode == BalancingMode.MINIMIZE_TRANSFERS:
            resource = next(
                (r for r in self.items if r.harvester_balance < 0),
                None
            )
        if not resource:
            resource = min(
                (r for r in self.items),
                key=lambda r : r.harvester_balance,
                default=None
            )
        if not resource:
            return False
        return resource.try_add(harvester)

    def try_remove_any(self) -> Optional[int]:
        if self.balancing_mode == BalancingMode.EVEN_DISTRIBUTION:
            resource = max(
                (r for r in reversed(self.items) if 0 < r.harvester_count),
                key = lambda r : r.harvester_balance,
                default = None
            )
            if not resource:
                return None
            return resource.try_remove_any()
        else:
            for resource in reversed(self.items):
                if 0 < resource.harvester_balance:
                    return resource.try_remove_any()
            for resource in reversed(self.items):
                if 0 < resource.harvester_count:
                    return resource.try_remove_any()
        return None

    def try_remove(self, harvester: int) -> bool:
        for resource in reversed(self.items):
            if resource.try_remove(harvester):
                return True
        return False

    @property
    def harvester_target(self) -> int:
        return sum(r.harvester_target for r in self.items)

    @property
    def harvesters(self) -> Iterable[int]:
        return (h for r in self.items for h in r.harvesters)

    @property
    def harvester_target(self) -> int:
        return sum(r.harvester_target for r in self.items)

    @property
    def income(self) -> float:
        return sum(r.income for r in self.items)

    def update(self):

        for resource in self.items:
            resource.update()

        # if bot.debug:
        #     for i, a in enumerate(self.items):
        #         for b in self.items[i+1:]:
        #             ha = list(a.harvesters)
        #             hb = list(b.harvesters)
        #             if any(set(ha).intersection(hb)):
        #                 raise Error

        super().update()

        self.remaining = sum(r.remaining for r in self.items)
        
        if self.balancing_mode != BalancingMode.NONE:
            if harvester := self.try_remove_any():
                self.try_add(harvester)
