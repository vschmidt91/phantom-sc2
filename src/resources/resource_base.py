from __future__ import annotations

from abc import ABC, abstractproperty
from typing import Iterable, TYPE_CHECKING

from sc2.position import Point2
from src.modules.module import AIModule

if TYPE_CHECKING:
    from src.ai_base import AIBase


class ResourceBase(AIModule, ABC):
    def __init__(self, ai: AIBase, position: Point2) -> None:
        super().__init__(ai)
        self.position = position

    @abstractproperty
    def harvester_target(self) -> int:
        raise NotImplementedError()

    @abstractproperty
    def remaining(self) -> int:
        raise NotImplementedError()

    def __hash__(self) -> int:
        return hash(self.position)

    def flatten(self) -> Iterable["ResourceBase"]:
        yield self
