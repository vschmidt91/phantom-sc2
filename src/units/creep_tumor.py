from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sc2.unit import Unit, UnitCommand

from ..behaviors.creep import CreepBehavior

if TYPE_CHECKING:
    from ..ai_base import AIBase


class CreepTumor(CreepBehavior):
    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)

    def get_command(self) -> Optional[UnitCommand]:
        return self.spread_creep()
