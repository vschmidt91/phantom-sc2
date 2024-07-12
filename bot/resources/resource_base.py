from __future__ import annotations

from abc import abstractmethod
from typing import Iterable, TYPE_CHECKING

from sc2.position import Point2


class ResourceBase:

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

    def flatten(self) -> Iterable['ResourceBase']:
        yield self
