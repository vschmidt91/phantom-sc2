
from __future__ import annotations
from typing import Iterable, Optional, TYPE_CHECKING
from abc import abstractmethod, abstractproperty

from sc2.position import Point2
from sc2.unit import Unit
from ..ai_component import AIComponent
from ..units.unit import AIUnit

if TYPE_CHECKING:
    from ..ai_base import AIBase

class ResourceBase(AIUnit):

    def __init__(self, ai: AIBase, position: Point2):
        super().__init__(ai, None)
        self.position = position
        self.harvester_target = 0

    def __hash__(self) -> int:
        return hash(self.position)

    @abstractproperty
    def remaining(self) -> int:
        raise NotImplementedError()

    @abstractmethod
    def update(self) -> None:
        raise NotImplementedError()

    def flatten(self) -> Iterable['ResourceBase']:
        yield self