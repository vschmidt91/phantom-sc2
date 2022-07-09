from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from sc2.unit import Unit

from .resource_base import ResourceBase

if TYPE_CHECKING:
    from ..ai_base import AIBase


class ResourceUnit(ResourceBase):

    def __init__(self, ai: AIBase, unit: Unit) -> None:
        super().__init__(ai, unit.position)
        self.unit: Optional[Unit] = unit

    @property
    def harvester_count(self) -> int:
        return self.ai.resource_manager.harvesters_by_resource.get(self, 0)

    @property
    def harvester_balance(self) -> int:
        return self.harvester_count - self.harvester_target
