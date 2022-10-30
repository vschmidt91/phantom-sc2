from __future__ import annotations
from dataclasses import dataclass

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable, Optional, List

from sc2.unit import Unit, UnitCommand
from sc2.position import Point2

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
        self.damage_taken: DamageTakenEvent = DamageTakenEvent(0, 0)

    @property
    def is_snapshot(self) -> bool:
        return self.unit.game_loop != self.ai.state.game_loop

    @abstractmethod
    def get_command(self) -> Optional[UnitCommand]:
        raise NotImplementedError()

    def on_took_damage(self, damage_taken: float):
        self.damage_taken = DamageTakenEvent(self.ai.time, damage_taken)


class IdleBehavior(AIUnit):

    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)

    def get_command(self) -> Optional[UnitCommand]:
        return None
