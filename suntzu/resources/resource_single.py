
from typing import Optional, Set, Union, Iterable
from sc2.position import Point2
from abc import ABC, abstractmethod

from .resource import Resource
from ..observation import Observation

class ResourceSingle(Resource):

    def __init__(self, position: Point2):
        super().__init__(position)
        self.harvester_set: Set[int] = set()

    def try_add(self, harvester: int) -> bool:
        if harvester in self.harvester_set:
            return False
        self.harvester_set.add(harvester)
        return True

    def try_remove_any(self) -> Optional[int]:
        if not any(self.harvesters):
            return None
        return self.harvester_set.pop()

    def try_remove(self, harvester: int) -> bool:
        if harvester in self.harvester_set:
            self.harvester_set.remove(harvester)
            return True
        else:
            return False

    @property
    def harvesters(self) -> Iterable[int]:
        return self.harvester_set