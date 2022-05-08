
from __future__ import annotations
from typing import Optional, TYPE_CHECKING

from sc2.unit import Unit, UnitCommand

from .unit import CommandableUnit
from ..modules.dodge import DodgeBehavior
from ..modules.combat import CombatBehavior
from ..modules.drop import DropBehavior
from ..modules.bile import BileBehavior
from ..modules.macro import MacroBehavior
from ..modules.creep import CreepBehavior
from ..behaviors.transfuse import TransfuseBehavior
from ..behaviors.inject import InjectBehavior
from ..behaviors.search import SearchBehavior
from ..behaviors.burrow import BurrowBehavior

if TYPE_CHECKING:
    from ..ai_base import AIBase

class Queen(DodgeBehavior, InjectBehavior, CreepBehavior, TransfuseBehavior, CombatBehavior, SearchBehavior):

    def __init__(self, ai: AIBase, tag: int):
        super().__init__(ai, tag)

    def get_command(self) -> Optional[UnitCommand]:
        return self.dodge() or self.inject() or self.spread_creep() or self.transfuse() or self.fight() or self.search()