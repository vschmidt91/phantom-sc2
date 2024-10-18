from abc import ABC, abstractmethod
from typing import Iterable

from sc2.position import Point2


class ResourceBase(ABC):
    def __init__(self, position: Point2):
        self.position = position

    @property
    @abstractmethod
    def harvester_target(self) -> int:
        raise NotImplementedError()

    @property
    @abstractmethod
    def remaining(self) -> int:
        raise NotImplementedError()

    def __hash__(self) -> int:
        return hash(self.position)

    def flatten(self) -> Iterable["ResourceBase"]:
        yield self
