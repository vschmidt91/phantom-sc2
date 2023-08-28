from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from sc2.unit import Unit, UnitCommand, UnitTypeId

from src.tools.observable import Event, Observable

if TYPE_CHECKING:
    from ..ai_base import AIBase


@dataclass
class UnitChangedEvent(Event):
    unit: AIUnit
    previous: Unit


class Behavior(ABC):
    def __init__(self, unit: "AIUnit") -> None:
        self.unit = unit

    @property
    def ai(self) -> AIBase:
        return self.unit.ai

    @abstractmethod
    def get_command(self) -> Optional[UnitCommand]:
        raise NotImplementedError()


class AIUnit:
    def __init__(self, ai: AIBase, state: Unit):
        self.ai = ai
        self.state: Unit = state
        self.behavior: Optional[Behavior] = None
        self.on_damage_taken = Observable[UnitChangedEvent]()
        self.on_type_changed = Observable[UnitChangedEvent]()
        self.on_destroyed = Observable[UnitChangedEvent]()

    def update_state(self, new_state: Optional[Unit]) -> None:
        old_state = self.state
        if new_state is None:
            if (
                old_state.type_id == UnitTypeId.DRONE
                and old_state.tag not in self.ai.state.dead_units
            ):
                pass  # drone in extractor
            else:
                self.on_destroyed(UnitChangedEvent(self, old_state))
        else:
            self.state = new_state
            if new_state.type_id != old_state.type_id:
                self.on_type_changed(UnitChangedEvent(self, old_state))
            if (
                new_state.health + new_state.shield
                < old_state.shield + old_state.shield
            ):
                self.on_damage_taken(UnitChangedEvent(self, old_state))

    @property
    def is_snapshot(self) -> bool:
        return self.state.game_loop != self.ai.state.game_loop

    def __hash__(self) -> int:
        return hash(self.state.tag)
