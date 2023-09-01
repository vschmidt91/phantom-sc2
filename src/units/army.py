from __future__ import annotations

from typing import Optional
import random

from sc2.unit import UnitCommand

from src.units.unit import AIUnit

from ..behaviors.bile import BileBehavior
from ..behaviors.burrow import BurrowBehavior
from ..behaviors.overlord_drop import OverlordDropMemberBehavior
from ..behaviors.search import SearchBehavior
from ..modules.combat import CombatBehavior
from ..modules.dodge import DodgeBehavior
from ..modules.macro import MacroBehavior


class Army(
    DodgeBehavior,
    MacroBehavior,
    BurrowBehavior,
    BileBehavior,
    OverlordDropMemberBehavior,
    CombatBehavior,
    SearchBehavior,
):
    def __init__(self, unit: AIUnit):
        super().__init__(unit)

    def get_command(self) -> Optional[UnitCommand]:
        if command := self.dodge():
            return command
        elif command := self.macro():
            return command
        elif command := self.burrow():
            return command
        elif command := self.bile():
            return command
        elif command := self.execute_overlord_drop():
            return command
        elif command := self.fight():
            return command
        elif self.ai.time < 8 * 60 and self.unit.state.is_idle:
            return self.unit.state.attack(
                random.choice(self.ai.enemy_start_locations)
            )
        elif command := self.search():
            return command
        else:
            return None
