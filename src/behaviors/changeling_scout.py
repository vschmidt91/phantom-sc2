from __future__ import annotations

from typing import Optional

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit
from sc2.unit_command import UnitCommand

from ..constants import ENERGY_COST
from ..units.unit import Behavior


class SpawnChangelingBehavior(Behavior):
    def __init__(self, state: Unit):
        super().__init__(state)

    def spawn_changeling(self) -> Optional[UnitCommand]:
        if self.unit.state.type_id not in {
            UnitTypeId.OVERSEER,
            UnitTypeId.OVERSEERSIEGEMODE,
        }:
            return None
        if not self.ai.in_pathing_grid(self.unit.state):
            return None
        ability = AbilityId.SPAWNCHANGELING_SPAWNCHANGELING
        if self.unit.state.energy < ENERGY_COST[ability]:
            return None
        return self.unit.state(ability)
