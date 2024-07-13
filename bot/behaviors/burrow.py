from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.unit_command import UnitCommand

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

        if self.unit.is_burrowed:
            if self.unit.health_percentage == 1 or self.unit.is_revealed:
                return self.unit(AbilityId.BURROWUP)
        elif self.unit.health_percentage < 1 / 3 and self.unit.weapon_cooldown and not self.unit.is_revealed:
            return self.unit(AbilityId.BURROWDOWN)

        return None
