from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from sc2.unit import Unit, UnitCommand

from ..behaviors.inject import InjectBehavior
from ..behaviors.search import SearchBehavior
from ..behaviors.transfuse import TransfuseBehavior
from ..modules.combat import CombatBehavior
from ..modules.creep import CreepBehavior
from ..modules.dodge import DodgeBehavior

if TYPE_CHECKING:
    from ..ai_base import AIBase


class Queen(DodgeBehavior, InjectBehavior, CreepBehavior, TransfuseBehavior, CombatBehavior, SearchBehavior):

    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)

    def get_command(self) -> Optional[UnitCommand]:
        return self.dodge() or self.inject() or self.spread_creep() or self.transfuse() or self.fight() or self.search()
