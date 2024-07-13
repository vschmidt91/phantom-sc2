from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Optional

from sc2.unit_command import UnitCommand

from ..constants import *
from ..units.unit import AIUnit

if TYPE_CHECKING:
    pass


class BurrowBehavior(AIUnit):
    def burrow(self) -> Optional[UnitCommand]:
        if self.unit.type_id not in {
            UnitTypeId.ROACH,
            UnitTypeId.ROACHBURROWED,
        }:
            return None

        if UpgradeId.BURROW not in self.ai.state.upgrades:
            return None

        # if UpgradeId.TUNNELINGCLAWS not in self.ai.state.upgrades:
        #     return None

        if self.unit.is_burrowed:
            if self.unit.health_percentage == 1 or self.unit.is_revealed:
                return self.unit(AbilityId.BURROWUP)
        elif self.unit.health_percentage < 1 / 3 and self.unit.weapon_cooldown and not self.unit.is_revealed:
            return self.unit(AbilityId.BURROWDOWN)

        return None
