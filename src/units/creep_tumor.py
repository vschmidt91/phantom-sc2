from __future__ import annotations

from typing import Optional

from sc2.unit import UnitCommand

from src.units.unit import AIUnit

from ..behaviors.creep import CreepBehavior


class CreepTumor(CreepBehavior):
    def __init__(self, unit: AIUnit) -> None:
        super().__init__(unit)

    def get_command(self) -> Optional[UnitCommand]:
        return self.spread_creep()
