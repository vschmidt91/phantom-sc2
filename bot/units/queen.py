from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from sc2.unit import Unit, UnitCommand

from ..behaviors.inject import InjectBehavior
from ..behaviors.search import SearchBehavior
from ..behaviors.transfuse import TransfuseBehavior
from ..modules.combat import CombatBehavior
from ..behaviors.creep import CreepBehavior
from ..modules.dodge import DodgeBehavior

if TYPE_CHECKING:
    from ..ai_base import AIBase


class Queen(DodgeBehavior, InjectBehavior, CreepBehavior, TransfuseBehavior, CombatBehavior):

    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)

    def get_command(self) -> Optional[UnitCommand]:
        if command := self.dodge():
            return command
        elif (
            (self.ai.supply_used + self.ai.larva.amount < 200)
            and (0 == self.ai.combat.ground_dps[self.unit.position.rounded])
            and (command := self.inject())
        ):
            return command
        elif (
            0 == self.ai.combat.ground_dps[self.unit.position.rounded]
            and (command := self.spread_creep())
        ):
            return command
        elif command := self.transfuse():
            return command
        elif command := self.fight():
            return command
        else:
            return None
