from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit, UnitCommand

from ..modules.macro import MacroBehavior

if TYPE_CHECKING:
    from ..ai_base import AIBase


class Structure(MacroBehavior):

    def get_command(self) -> Optional[UnitCommand]:
        if self.unit.health_percentage < 0.05:
            return self.unit(AbilityId.CANCEL)
        else:
            return self.macro()


class Larva(Structure):
    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)
