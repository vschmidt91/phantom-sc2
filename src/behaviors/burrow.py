from __future__ import annotations

from abc import ABC
from typing import Optional, TYPE_CHECKING

from sc2.unit_command import UnitCommand

from .behavior import Behavior
from ..constants import *

if TYPE_CHECKING:
    pass


class BurrowBehavior(ABC, Behavior):

    def burrow(self) -> Optional[UnitCommand]:

        if self.unit.type_id not in {UnitTypeId.ROACH, UnitTypeId.ROACHBURROWED}:
            return None

        if UpgradeId.BURROW not in self.ai.state.upgrades:
            return None

        if UpgradeId.TUNNELINGCLAWS in self.ai.state.upgrades:
            return None

        if self.unit.is_burrowed:
            if self.unit.health_percentage == 1 or self.unit.is_revealed:
                return self.unit(AbilityId.BURROWUP)
        else:
            if (
                    self.unit.health_percentage < 1 / 3
                    and self.unit.weapon_cooldown
                    and not self.unit.is_revealed
            ):
                return self.unit(AbilityId.BURROWDOWN)
