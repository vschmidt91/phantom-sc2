
from __future__ import annotations
from optparse import Option
from typing import Optional, TYPE_CHECKING, Set
from abc import abstractproperty

from sc2.position import Point2
from sc2.unit import Unit
from src.units.unit import AIUnit
from ..ai_component import AIComponent
from .resource_base import ResourceBase

if TYPE_CHECKING:
    from ..ai_base import AIBase

class ResourceUnit(ResourceBase):
    
    def __init__(self, ai: AIBase, position: Point2) -> None:
        super().__init__(ai, position)

    @property
    def harvester_count(self) -> int:
        return self.ai.resource_manager.harvesters_by_resource.get(self, 0)

    @property
    def harvester_balance(self) -> int:
        return self.harvester_count - self.harvester_target

    @property
    def unit(self) -> Optional[Unit]:
        return self.ai.unit_manager.resource_by_position.get(self.position)