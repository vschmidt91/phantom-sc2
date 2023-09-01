from __future__ import annotations
import logging
from typing import Optional

from sc2.unit import UnitCommand
from sc2.ids.ability_id import AbilityId

from src.units.unit import AIUnit

from ..behaviors.creep import CreepBehavior


class CreepTumor(CreepBehavior):

    def __init__(self, unit: AIUnit) -> None:
        super().__init__(unit)
        self.creation_step = self.ai.state.game_loop
        self.is_used = False

    def get_command(self) -> Optional[UnitCommand]:
        command = self.spread_creep()
        if command:
            self.is_used = True
        return command

    def can_spread_creep(self) -> bool:
        if self.is_used:
            return False
        age = self.ai.state.game_loop - self.creation_step
        if age < 548:
            return False
        if self.ai.debug and AbilityId.BUILD_CREEPTUMOR_TUMOR not in self.ai.available_abilities[self.unit.state]:
            logging.error("Expected Creep Tumor to be active, but it is not.")
        return True