from __future__ import annotations

from typing import Optional

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.ability_id import AbilityId
from sc2.unit_command import UnitCommand

from ..units.unit import AIUnit, Behavior


class BurrowBehavior(Behavior):
    def __init__(self, unit: AIUnit) -> None:
        super().__init__(unit)

    def burrow(self) -> Optional[UnitCommand]:
        if self.unit.state.type_id not in {
            UnitTypeId.ROACH,
            UnitTypeId.ROACHBURROWED,
        }:
            return None

        if UpgradeId.BURROW not in self.ai.state.upgrades:
            return None

        # if UpgradeId.TUNNELINGCLAWS not in self.ai.state.upgrades:
        #     return None

        if self.unit.state.is_burrowed:
            if self.unit.state.health_percentage == 1 or self.unit.state.is_revealed:
                return self.unit.state(AbilityId.BURROWUP)
        elif (
            self.unit.state.health_percentage < 1 / 3
            and self.unit.state.weapon_cooldown
            and not self.unit.state.is_revealed
        ):
            return self.unit.state(AbilityId.BURROWDOWN)

        return None
