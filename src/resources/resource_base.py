
from __future__ import annotations
from typing import Any, Optional, Set, Union, Iterable, Tuple, TYPE_CHECKING

from sc2.position import Point2
from abc import ABC, abstractmethod
from ..ai_component import AIComponent

if TYPE_CHECKING:
    from ..ai_base import AIBase

class ResourceBase(AIComponent):

    def __init__(self, ai: AIBase, position: Point2) -> None:
        super().__init__(ai)
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
    def harvester_target(self) -> int:
        raise NotImplementedError()

    @property
    @abstractmethod
    def income(self) -> float:
        raise NotImplementedError()

    @property
    @abstractmethod
    def get_resource(self, harvester: int) -> Optional['ResourceBase']:
        raise NotImplementedError()

    @property
    def harvester_count(self) -> int:
        return sum(1 for _ in self.harvesters)

    @property
    def harvester_balance(self) -> int:
        return self.harvester_count - self.harvester_target

    def update(self) -> None:
        pass

    def try_transfer_to(self, other: 'ResourceBase') -> Optional[int]:
        if not (harvester := self.try_remove_any()):
            return None
        if other.try_add(harvester):
            return harvester
        if self.try_add(harvester):
            return None
        return None