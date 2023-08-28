from __future__ import annotations

from typing import Optional

from sc2.ids.ability_id import AbilityId
from sc2.unit import UnitCommand

from src.units.unit import UnitChangedEvent

from ..behaviors.inject import InjectReciever
from ..modules.macro import MacroBehavior
from .unit import AIUnit


class Structure(MacroBehavior):
    def __init__(self, unit: AIUnit):
        super().__init__(unit)
        self.cancel: bool = False
        self.unit.on_damage_taken.subscribe(self.cancel_if_under_threat)

    def get_command(self) -> Optional[UnitCommand]:
        if self.cancel:
            return self.unit.state(AbilityId.CANCEL)
        else:
            return self.macro()

    def cancel_if_under_threat(self, event: UnitChangedEvent):
        if self.unit.state.health_percentage < 0.1:
            self.cancel = True


class Hatchery(Structure, InjectReciever):
    def wants_inject(self) -> bool:
        if not self.unit.state.is_ready:
            return False
        # if BuffId.QUEENSPAWNLARVATIMER in self.state.buffs:
        #     return False
        if 20 < self.ai.larva.amount:
            return False
        return True


class Larva(Structure):
    def __init__(self, unit: AIUnit):
        super().__init__(unit)
