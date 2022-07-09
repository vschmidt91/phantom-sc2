from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit, UnitCommand

from ..modules.macro import MacroBehavior

if TYPE_CHECKING:
    from ..ai_base import AIBase


class Structure(MacroBehavior):

    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)
        self.cancel: bool = False

    def get_command(self) -> Optional[UnitCommand]:
        if self.cancel:
            return self.unit(AbilityId.CANCEL)
        return self.macro()


class Larva(Structure):

    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)
