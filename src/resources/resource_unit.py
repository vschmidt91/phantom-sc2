from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from sc2.unit import Unit

from .resource_base import ResourceBase


class ResourceUnit(ResourceBase):

    def __init__(self,  unit: Unit) -> None:
        super().__init__(unit.position)
        self.unit: Optional[Unit] = unit