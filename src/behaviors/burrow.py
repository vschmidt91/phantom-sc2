from __future__ import annotations

from abc import ABC
from typing import Optional, TYPE_CHECKING

from sc2.unit_command import UnitCommand

from ..units.unit import AIUnit
from ..constants import *

if TYPE_CHECKING:
    pass


class BurrowBehavior(AIUnit):

    def burrow(self) -> Optional[UnitCommand]:

        if self.state.type_id not in {
            UnitTypeId.ROACH,
            UnitTypeId.ROACHBURROWED,
        }:
            return None

        if UpgradeId.BURROW not in self.ai.state.upgrades:
            return None

        # if UpgradeId.TUNNELINGCLAWS not in self.ai.state.upgrades:
        #     return None

        if self.state.is_burrowed:
            if self.state.health_percentage == 1 or self.state.is_revealed:
                return self.state(AbilityId.BURROWUP)
        elif (
            self.state.health_percentage < 1 / 3
            and self.state.weapon_cooldown
            and not self.state.is_revealed
        ):
            return self.state(AbilityId.BURROWDOWN)

        return None
