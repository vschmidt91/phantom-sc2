
from __future__ import annotations
from typing import Optional, TYPE_CHECKING

from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit, UnitCommand

from .unit import CommandableUnit
from ..modules.dodge import DodgeBehavior
from ..modules.scout import ScoutBehavior
from ..modules.macro import MacroBehavior
from ..modules.drop import DropBehavior
from ..behaviors.survive import SurviveBehavior
from ..behaviors.changeling_scout import SpawnChangelingBehavior
from ..modules.combat import CombatBehavior

if TYPE_CHECKING:
    from ..ai_base import AIBase

class Overlord(DodgeBehavior, MacroBehavior, SpawnChangelingBehavior, ScoutBehavior, DropBehavior, SurviveBehavior, CombatBehavior):

    def __init__(self, ai: AIBase, tag: int):
        super().__init__(ai, tag)

    def get_command(self) -> Optional[UnitCommand]:
        if self.unit.type_id == UnitTypeId.OVERLORD:
            return self.dodge() or self.macro() or self.survive() or self.scout()
        elif self.unit.type_id == UnitTypeId.OVERLORDTRANSPORT:
            return self.dodge() or self.survive() or self.drop()
        elif self.unit.type_id in { UnitTypeId.OVERSEER, UnitTypeId.OVERSEERSIEGEMODE }:
            return self.dodge() or self.spawn_changeling() or self.scout() or self.fight()