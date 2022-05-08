
from __future__ import annotations
from typing import Optional, TYPE_CHECKING

from sc2.unit import Unit, UnitCommand
from src.units.unit import CommandableUnit

from ..behaviors.behavior import Behavior
from ..modules.dodge import DodgeBehavior
from ..modules.macro import MacroBehavior
from ..modules.combat import CombatBehavior
from ..behaviors.gather import GatherBehavior

if TYPE_CHECKING:
    from ..ai_base import AIBase

class Worker(DodgeBehavior, CombatBehavior, MacroBehavior, GatherBehavior):
    
    def __init__(self, ai: AIBase, tag: int):
        super().__init__(ai, tag)
        self.fight_enabled = False

    def get_command(self) -> Optional[UnitCommand]:
        return self.dodge() or self.fight() or self.macro() or self.gather()