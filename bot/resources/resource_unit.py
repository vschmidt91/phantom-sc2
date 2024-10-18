from abc import ABC
from typing import Optional

from sc2.unit import Unit

from .resource_base import ResourceBase


class ResourceUnit(ResourceBase, ABC):
    def __init__(self, unit: Unit) -> None:
        super().__init__(unit.position)
        self.unit: Optional[Unit] = unit
