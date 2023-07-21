from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit, UnitCommand
from src.units.unit import UnitChangedEvent

from ..modules.macro import MacroBehavior

if TYPE_CHECKING:
    from ..ai_base import AIBase


class Structure(MacroBehavior):
    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)
        self.cancel: bool = False
        self.on_damage_taken.subscribe(self.cancel_if_under_threat)

    def get_command(self) -> Optional[UnitCommand]:
        if self.cancel:
            return self.state(AbilityId.CANCEL)
        else:
            return self.macro()

    def cancel_if_under_threat(self, event: UnitChangedEvent):
        if self.state.health_percentage < 0.1:
            self.cancel = True


class Larva(Structure):
    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)
