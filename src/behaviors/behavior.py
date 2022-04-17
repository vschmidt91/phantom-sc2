from __future__ import annotations

from typing import Iterable, Optional, List, TYPE_CHECKING, Callable, Generic, TypeVar, Dict
from sc2.unit import Unit, UnitCommand
from abc import ABC, abstractmethod
from enum import Enum

from ..ai_component import AIComponent

if TYPE_CHECKING:
    from ..ai_base import AIBase

class Behavior(AIComponent):

    def __init__(self, ai: AIBase, unit_tag: int) -> None:
        super().__init__(ai)
        self.unit_tag: int = unit_tag

    def execute(self) -> Optional[UnitCommand]:
        if unit := self.ai.unit_by_tag.get(self.unit_tag):
            return self.execute_single(unit)
        else:
            return None

    def execute_single(self, unit: Unit) -> Optional[UnitCommand]:
        return None

class LambdaBehavior(Behavior):

    def __init__(self, ai: AIBase, unit_tag: int, func: Callable[[], Optional[UnitCommand]]):
        super().__init__(ai, unit_tag)
        self.func: Callable[[Unit], Optional[UnitCommand]] = func

    def execute_single(self, unit: Unit) -> Optional[UnitCommand]:
        return self.func(unit)
        
T = TypeVar('T')

class SwitchBehavior(Behavior, Generic[T]):

    def __init__(self, ai: AIBase, unit_tag: int, selector: Callable[[Unit], T], cases: Dict[T, Behavior]):
        super().__init__(ai, unit_tag)
        self.selector: Callable[[Unit], T] = selector
        self.cases: Dict[T, Behavior] = cases

    def execute_single(self, unit: Unit) -> Optional[UnitCommand]:
        select = self.selector(unit)
        if behavior := self.cases.get(select):
            return behavior.execute()

class BehaviorSequence(Behavior):

    def __init__(self, ai: AIBase, unit_tag: int, behaviors: List[Behavior]) -> None:
        super().__init__(ai, unit_tag)
        self.behaviors = behaviors

    def execute(self) -> Optional[UnitCommand]:
        for behavior in self.behaviors:
            if command := behavior.execute():
                return command
        return None