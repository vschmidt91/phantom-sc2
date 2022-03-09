
from typing import Any, Optional, Set, Union, Iterable, Tuple

from s2clientprotocol.error_pb2 import Error
from sc2.position import Point2
from abc import ABC, abstractmethod

class ResourceBase(ABC):

    def __init__(self, position: Point2):
        self.position: Point2 = position
        self.remaining: Optional[int] = 0

    @abstractmethod
    def try_add(self, harvester: int) -> bool:
        raise NotImplementedError()

    @abstractmethod
    def try_remove_any(self) -> Optional[int]:
        raise NotImplementedError()

    @abstractmethod
    def try_remove(self, harvester: int) -> bool:
        raise NotImplementedError()

    @property
    @abstractmethod
    def harvesters(self) -> Iterable[int]:
        raise NotImplementedError()

    @property
    @abstractmethod
    def harvester_target(self):
        raise NotImplementedError()

    @property
    @abstractmethod
    def income(self):
        raise NotImplementedError()

    @property
    @abstractmethod
    def get_resource(self, harvester: int) -> Optional['ResourceBase']:
        raise NotImplementedError()

    @property
    def harvester_count(self):
        return sum(1 for _ in self.harvesters)

    @property
    def harvester_balance(self):
        return self.harvester_count - self.harvester_target

    def update(self, bot):
        pass

    def try_transfer_to(self, other: 'ResourceBase') -> Optional[int]:
        if not (harvester := self.try_remove_any()):
            return None
        if other.try_add(harvester):
            return harvester
        if self.try_add(harvester):
            return None
        return None