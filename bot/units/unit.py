from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from sc2.unit import Unit, UnitCommand

if TYPE_CHECKING:
    from ..ai_base import AIBase


@dataclass
class DamageTakenEvent:
    time: float
    amount: float


class AIUnit(ABC):
    def __init__(self, ai: AIBase, unit: Unit):
        self.ai = ai
        self.unit = unit

    @property
    def is_snapshot(self) -> bool:
        return self.unit.game_loop != self.ai.state.game_loop

    @abstractmethod
    def get_command(self) -> Optional[UnitCommand]:
        raise NotImplementedError()


class IdleBehavior(AIUnit):
    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)

    def get_command(self) -> Optional[UnitCommand]:
        return None
