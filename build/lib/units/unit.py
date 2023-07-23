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


class AIUnit(ABC):
    def __init__(self, ai: AIBase, state: Unit):
        self.ai = ai
        self.state = state
        self.on_damage_taken = Observable[UnitChangedEvent]()
        self.on_type_changed = Observable[UnitChangedEvent]()
        self.on_destroyed = Observable[UnitChangedEvent]()

    def on_step(self) -> None:
        old_state = self.state
        new_state = self.ai.unit_manager.unit_by_tag.get(self.state.tag, None)
        event = UnitChangedEvent(self, old_state)
        if new_state:
            self.state = new_state
            if new_state.type_id != old_state.type_id:
                self.on_type_changed(event)
            if (
                new_state.health + new_state.shield
                < old_state.shield + old_state.shield
            ):
                self.on_damage_taken(event)
        else:
            if (
                old_state.type_id == UnitTypeId.DRONE
                and old_state.tag not in self.ai.state.dead_units
            ):
                pass  # drone in extractor
            else:
                self.on_destroyed(event)

    @property
    def is_snapshot(self) -> bool:
        return self.state.game_loop != self.ai.state.game_loop

    @abstractmethod
    def get_command(self) -> Optional[UnitCommand]:
        raise NotImplementedError()

    def __hash__(self) -> int:
        return hash(self.state.tag)


class IdleBehavior(AIUnit):
    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)

    def get_command(self) -> Optional[UnitCommand]:
        return None
