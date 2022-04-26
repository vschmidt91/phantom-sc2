
from __future__ import annotations
from typing import Optional, TYPE_CHECKING

from sc2.unit import Unit, UnitCommand

from .unit import AIUnit
from ..modules.dodge import DodgeBehavior
from ..modules.scout import ScoutBehavior, DetectBehavior
from ..modules.macro import MacroBehavior
from ..modules.drop import DropBehavior
from ..behaviors.survive import SurviveBehavior
from ..behaviors.changeling_scout import SpawnChangelingBehavior

if TYPE_CHECKING:
    from ..ai_base import AIBase

class Overlord(DodgeBehavior, MacroBehavior, SpawnChangelingBehavior, DetectBehavior, DropBehavior, SurviveBehavior, ScoutBehavior):

    def __init__(self, ai: AIBase, tag: int):
        super().__init__(ai, tag)

    def get_command(self) -> Optional[UnitCommand]:
        return self.dodge() or self.macro() or self.drop() or self.survive() or self.scout()