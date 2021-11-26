
from typing import Iterable, Optional, List

from sc2.unit import Unit, UnitCommand
from abc import ABC, abstractmethod
from enum import Enum

class BehaviorResult(Enum):
    ONGOING = 1
    SUCCESS = 2
    FAILURE = 3

class Behavior(ABC):

    def __init__(self):
        pass

    @abstractmethod
    def execute(self, unit: Unit) -> BehaviorResult:
        raise NotImplementedError

class BehaviorSequence(Behavior):

    def __init__(self, behaviors: List[Behavior]):
        self.behaviors = behaviors

    def execute(self, unit: Unit) -> BehaviorResult:
        for behavior in self.behaviors:
            result = behavior.execute(unit)
            if result in { BehaviorResult.ONGOING, BehaviorResult.FAILURE }:
                return result
        return BehaviorResult.SUCCESS

class BehaviorSelector(Behavior):

    def __init__(self, behaviors: List[Behavior]):
        self.behaviors = behaviors

    def execute(self, unit: Unit) -> BehaviorResult:
        for behavior in self.behaviors:
            result = behavior.execute(unit)
            if result in { BehaviorResult.ONGOING, BehaviorResult.SUCCESS }:
                return result
        return BehaviorResult.FAILURE