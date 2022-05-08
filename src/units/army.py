
from __future__ import annotations
from typing import Optional, TYPE_CHECKING

from sc2.unit import Unit, UnitCommand
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from .unit import CommandableUnit
from ..modules.dodge import DodgeBehavior
from ..modules.combat import CombatBehavior
from ..modules.drop import DropBehavior
from ..modules.bile import BileBehavior
from ..modules.macro import MacroBehavior
from ..behaviors.search import SearchBehavior
from ..behaviors.burrow import BurrowBehavior

if TYPE_CHECKING:
    from ..ai_base import AIBase

class Army(DodgeBehavior, MacroBehavior, BurrowBehavior, BileBehavior, DropBehavior, CombatBehavior, SearchBehavior):

    def __init__(self, ai: AIBase, tag: int):
        super().__init__(ai, tag)

    def get_command(self) -> Optional[UnitCommand]:
        if command := self.dodge():
            return command
        elif command := self.macro():
            return command
        elif (
            UpgradeId.BURROW in self.ai.state.upgrades
            and (command := self.burrow())
        ):
            return command
        elif (
            self.unit
            and self.unit.type_id == UnitTypeId.RAVAGER
            and (command := self.bile())
        ):
            return command
        elif command := self.drop():
            return command
        elif command := self.fight():
            return command
        elif command := self.search():
            return command