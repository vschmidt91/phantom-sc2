
from typing import Iterable, List, TypeVar, Generic

from .tactic_base import TacticBase
from ..common import CommonAI

T = TypeVar('T', bound=TacticBase)

class TacticGroup(TacticBase, Generic[T], Iterable[T]):

    def __init__(self, bot: CommonAI, tactics: List[T]):
        self.tactics = tactics
        super().__init__(bot)

    def __iter__(self):
        return iter(self.tactics)

    def __getitem__(self, index):
        return self.tactics[index]

    def __len__(self):
        return len(self.tactics)
        
    def execute(self):
        for tactic in self.tactics:
            tactic.execute()