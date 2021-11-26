
from typing import Dict, Iterable, Set, List, Optional, TypeVar, Generic
from itertools import chain

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
        self.balance_aggressively: bool = False

    def __iter__(self):
        return iter(self.items)

    def __getitem__(self, index):
        return self.items[index]

    def __len__(self):
        return len(self.items)

    def get_resource(self, harvester: int) -> Optional[ResourceBase]:
        for item in self.items:
            result = item.get_resource(harvester)
            if result:
                return result
        return None

    def try_add(self, harvester: int) -> bool:
        resource = min(
            (r for r in self.items if 0 < r.remaining),
            key=lambda r : r.harvester_balance,
            default=None
        )
        if not resource:
            return False
        return resource.try_add(harvester)

    def try_remove_any(self) -> Optional[int]:
        resource = max(
            (r for r in self.items if 0 < r.harvester_count),
            key = lambda r : r.harvester_balance,
            default=None
        )
        if not resource:
            return None
        return resource.try_remove_any()

    def try_remove(self, harvester: int) -> bool:
        return any(r.try_remove(harvester) for r in self.items)

    @property
    def harvesters(self) -> Iterable[int]:
        return (h in r.harvesters for r in self.items for h in r.harvesters)

    @property
    def harvester_target(self):
        return sum(r.harvester_target for r in self.items)

    def do_worker_split(self, harvesters: Set[Unit]):
        for _ in range(len(harvesters)):
            for resource in self.items:
                harvester = min(
                    harvesters,
                    key=lambda h:h.position.distance_to(resource.position),
                    default=None
                )
                if not harvester:
                    return
                harvesters.remove(harvester)
                resource.harvesters.add(harvester.tag)

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

        super().update(bot)

        self.remaining = sum(r.remaining for r in self.items)

        while True:
            resource_from = max(
                (r for r in self.items if 0 < r.harvester_count),
                key=lambda r:r.harvester_balance,
                default=None
            )
            if not resource_from:
                break
            resource_to = min(self.items, key=lambda r:r.harvester_balance)
            if self.balance_aggressively:
                if resource_from.harvester_count == 0:
                    break
                if resource_from.harvester_balance - 1 <= resource_to.harvester_balance + 1:
                    break
            else:
                if resource_from.harvester_balance <= 0:
                    break
                if 0 <= resource_to.harvester_balance:
                    break
            # print('transfer internal')
            if not resource_from.try_transfer_to(resource_to):
                print('transfer internal failed')
                break