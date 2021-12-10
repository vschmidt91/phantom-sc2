from __future__ import annotations

from typing import Iterable, Optional, List, TYPE_CHECKING, Callable, Generic, TypeVar, Dict
from sc2.unit import Unit, UnitCommand
from abc import ABC, abstractmethod
from enum import Enum

from ..ai_component import AIComponent

if TYPE_CHECKING:
    from ..ai_base import AIBase

class BehaviorResult(Enum):
    ONGOING = 1
    SUCCESS = 2
    FAILURE = 3

class Behavior(ABC):

    @abstractmethod
    def execute(self) -> BehaviorResult:
        raise NotImplementedError

class UnitBehavior(Behavior):

    def __init__(self, ai: AIBase, unit_tag: int):
        super().__init__()
        self.ai: AIBase = ai
        self.unit_tag: int = unit_tag

    def execute(self) -> BehaviorResult:
        unit = self.ai.unit_by_tag.get(self.unit_tag)
        if not unit:
            return BehaviorResult.FAILURE
        return self.execute_single(unit)

    @abstractmethod
    def execute_single(self, unit: Unit) -> BehaviorResult:
        raise NotImplementedError

class LambdaBehavior(Behavior):

    def __init__(self, func: Callable[[], BehaviorResult]):
        super().__init__()
        self.func: Callable[[], BehaviorResult] = func

    def execute(self) -> BehaviorResult:
        return self.func()
        
T = TypeVar('T')

class SwitchBehavior(UnitBehavior, Generic[T]):

    def __init__(self, ai: AIBase, unit_tag: int, selector: Callable[[Unit], T], cases: Dict[T, Behavior]):
        super().__init__(ai, unit_tag)
        self.selector: Callable[[Unit], T] = selector
        self.cases: Dict[T, Behavior] = cases

    def execute_single(self, unit: Unit) -> BehaviorResult:
        case = self.selector(unit)
        behavior = self.cases[case]
        return behavior.execute()

class BehaviorSequence(Behavior):

    def __init__(self, behaviors: List[Behavior]):
        super().__init__()
        self.behaviors = behaviors

    def execute(self) -> BehaviorResult:
        for behavior in self.behaviors:
            result = behavior.execute()
            if result in { BehaviorResult.ONGOING, BehaviorResult.FAILURE }:
                return result
        return BehaviorResult.SUCCESS

class BehaviorSelector(Behavior):

    def __init__(self, behaviors: List[Behavior]):
        super().__init__()
        self.behaviors = behaviors

    def execute(self) -> BehaviorResult:
        for behavior in self.behaviors:
            result = behavior.execute()
            if result in { BehaviorResult.ONGOING, BehaviorResult.SUCCESS }:
                return result
        return BehaviorResult.FAILURE