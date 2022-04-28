
from __future__ import annotations
from optparse import Option
from typing import Optional, TYPE_CHECKING
from abc import abstractproperty

from sc2.position import Point2
from sc2.unit import Unit
from ..ai_component import AIComponent
from .resource_base import ResourceBase

if TYPE_CHECKING:
    from ..ai_base import AIBase

class ResourceUnit(ResourceBase):
    
    def __init__(self, ai: AIBase, position: Point2) -> None:
        super().__init__(ai, position)

    @abstractproperty
    def gather_target(self) -> Optional[Unit]:
        raise NotImplementedError()

    @property
    def unit(self) -> Optional[Unit]:
        return self.ai.resource_by_position.get(self.position)