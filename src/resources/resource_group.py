
from typing import Dict, Iterable, Set, List, Optional, TypeVar, Generic, Tuple
from itertools import chain
import math

from google.protobuf.descriptor import Error

from sc2.unit import Unit
from sc2.position import Point2

from .resource_base import ResourceBase
from ..utils import center

T = TypeVar('T', bound=ResourceBase)

class ResourceGroup(ResourceBase, Generic[T], Iterable[T]):

    def __init__(self, items: List[T], position: Optional[Point2] = None):
        if position == None:
            position = center((r.position for r in items))
        super().__init__(position)
        self.items: List[T] = items
        self.balance_evenly: bool = False

    def __iter__(self):
        return iter(self.items)

    def __getitem__(self, index):
        return self.items[index]

    def __len__(self):
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
        if self.balance_evenly:
            resource = None
        else:
            resource = next(
                (r for r in self.items if r.harvester_balance < 0),
                None
            )
        if not resource:
            resource = min(
                (r for r in self.items),
                key=lambda r : r.harvester_balance - math.exp(-r.position.distance_to(self.position)),
                default=None
            )
        if not resource:
            return False
        return resource.try_add(harvester)

    def try_remove_any(self, force: bool = True) -> Optional[int]:
        if self.balance_evenly:
            resource = max(
                (r for r in self.items if 0 < r.harvester_count),
                key = lambda r : r.harvester_balance + math.exp(-r.position.distance_to(self.position)),
                default = None
            )
            if (
                resource
                and (force or 0 < resource.harvester_balance)
            ):
                return resource.try_remove_any(force=force)
        else:
            for resource in reversed(self.items):
                if 0 < resource.harvester_balance:
                    return resource.try_remove_any(force=force)
            if force:
                for resource in reversed(self.items):
                    if 0 < resource.harvester_count:
                        return resource.try_remove_any(force=force)
        return None

    def try_remove(self, harvester: int) -> bool:
        for resource in reversed(self.items):
            if resource.try_remove(harvester):
                return True
        return False

    @property
    def harvester_target(self):
        return sum(r.harvester_target for r in self.items)

    @property
    def harvesters(self) -> Iterable[int]:
        return (h for r in self.items for h in r.harvesters)

    @property
    def harvester_target(self) -> int:
        return sum(r.harvester_target for r in self.items)

    @property
    def income(self):
        return sum(r.income for r in self.items)

    def update(self, bot):

        for resource in self.items:
            resource.update(bot)

        if bot.debug:
            for i, a in enumerate(self.items):
                for b in self.items[i+1:]:
                    ha = list(a.harvesters)
                    hb = list(b.harvesters)
                    if any(set(ha).intersection(hb)):
                        raise Error

        super().update(bot)

        self.remaining = sum(r.remaining for r in self.items)

        # harvesters_transfered = set()
        # while True:
        #     if not (harvester := self.try_remove_any()):
        #         break
        #     if not self.try_add(harvester):
        #         break
        #     if harvester in harvesters_transfered:
        #         break
        #     harvesters_transfered.add(harvester)
        
        if harvester := self.try_remove_any(force=False):
            self.try_add(harvester)