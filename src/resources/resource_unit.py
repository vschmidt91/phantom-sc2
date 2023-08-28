from __future__ import annotations

import functools
from typing import Optional, TYPE_CHECKING
from sc2.position import Point2

from sc2.unit import Unit

if TYPE_CHECKING:
    from src.ai_base import AIBase

from .resource_base import ResourceBase


class ResourceUnit(ResourceBase):
    def __init__(self, ai: AIBase, position: Point2) -> None:
        super().__init__(ai, position)

    def on_step(self) -> None:
        return super().on_step()

    # @functools.cached_property
    @property
    def unit(self) -> Optional[Unit]:
        return self.ai.resource_manager.resource_unit_by_position.get(self.position)
