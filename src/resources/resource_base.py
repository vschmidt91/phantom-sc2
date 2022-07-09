from __future__ import annotations

from abc import abstractmethod
from typing import Iterable, TYPE_CHECKING

from sc2.position import Point2

from ..units.unit import AIUnit

if TYPE_CHECKING:
    from ..ai_base import AIBase


class ResourceBase(AIUnit):

    def __init__(self, ai: AIBase, position: Point2):
        super().__init__(ai, None)
        self.position = position

    @property
    @abstractmethod
    def harvester_target(self) -> int:
        raise NotImplementedError()

    def __hash__(self) -> int:
        return hash(self.position)

    @property
    @abstractmethod
    def remaining(self) -> int:
        raise NotImplementedError()

    def flatten(self) -> Iterable['ResourceBase']:
        yield self
