from __future__ import annotations
from typing import Optional, Set, Union, Iterable, Tuple, List, TYPE_CHECKING
from sc2.position import Point2
from abc import ABC, abstractmethod, abstractproperty

from .resource_base import ResourceBase
if TYPE_CHECKING:
    from ..ai_base import AIBase

class ResourceSingle(ResourceBase):

    def __init__(self, ai: AIBase, position: Point2, base_position: Point2) -> None:
        super().__init__(ai, position)
        self.harvester_list: List[int] = list()
        self.base_position: Point2 = base_position

    def get_resource(self, harvester: int) -> Optional[ResourceBase]:
        if harvester in self.harvesters:
            return self
        else:
            return None

    def try_add(self, harvester: int) -> bool:
        if harvester in self.harvester_list:
            return False
        self.harvester_list.append(harvester)
        return True

    def try_remove_any(self,) -> Optional[int]:
        if not any(self.harvesters):
            return None
        return self.harvester_list.pop()

    def try_remove(self, harvester: int) -> bool:
        if harvester in self.harvester_list:
            self.harvester_list.remove(harvester)
            return True
        else:
            return False

    @abstractproperty
    def harvest_duration(self) -> int:
        raise NotImplementedError

    @property
    def harvesters(self) -> Iterable[int]:
        return self.harvester_list