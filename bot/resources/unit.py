from abc import ABC, abstractmethod
from typing import Optional

from sc2.unit import Unit

from bot.resources.base import ResourceBase


class ResourceUnit(ResourceBase, ABC):
    def __init__(self, unit: Unit) -> None:
        super().__init__(unit.position)
        self.unit: Optional[Unit] = unit

    @property
    @abstractmethod
    def target_unit(self) -> Unit | None:
        raise NotImplementedError
