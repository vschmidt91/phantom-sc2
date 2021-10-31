
from typing import Optional, Set, Union, Iterable
from sc2.position import Point2
from abc import ABC, abstractmethod

from .observation import Observation

class Resource(object):

    def __init__(self, position: Point2):
        self.position: Point2 = position
        self.remaining: int = 0
        self.harvesters: Set[int] = set()

    @abstractmethod
    def update(self, observation: Observation):
        raise NotImplementedError()

    @property
    def harvester_count(self):
        return len(self.harvesters)

    @property
    @abstractmethod
    def harvester_target(self):
        raise NotImplementedError()

    @property
    def harvester_balance(self):
        return len(self.harvesters) - self.harvester_target

    def update(self, observation: Observation):
        pass