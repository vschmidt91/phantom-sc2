from __future__ import annotations

from typing import Optional

from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import UnitCommand

from ..behaviors.changeling_scout import SpawnChangelingBehavior
from ..behaviors.overlord_drop import OverlordDropBehavior
from ..behaviors.survive import SurviveBehavior
from ..modules.combat import CombatBehavior
from ..modules.dodge import DodgeBehavior
from ..modules.macro import MacroBehavior
from ..modules.scout import ScoutBehavior
from .unit import AIUnit


class Overlord(
    DodgeBehavior,
    MacroBehavior,
    SpawnChangelingBehavior,
    ScoutBehavior,
    SurviveBehavior,
    OverlordDropBehavior,
    CombatBehavior,
):
    def __init__(self, unit: AIUnit) -> None:
        super().__init__(unit)

    def get_command(self) -> Optional[UnitCommand]:
        if self.unit.state.type_id == UnitTypeId.OVERLORD:
            return self.dodge() or self.macro() or self.survive() or self.scout()
        elif self.unit.state.type_id == UnitTypeId.OVERLORDTRANSPORT:
            return self.dodge() or self.survive() or self.execute_overlord_drop()
        elif self.unit.state.type_id in {
            UnitTypeId.OVERSEER,
            UnitTypeId.OVERSEERSIEGEMODE,
        }:
            return (
                self.dodge() or self.spawn_changeling() or self.scout() or self.fight()
            )
        return None
