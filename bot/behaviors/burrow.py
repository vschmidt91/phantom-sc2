from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import numpy as np
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
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
            elif self.unit.type_id == UnitTypeId.ROACHBURROWED and UpgradeId.TUNNELINGCLAWS in self.ai.state.upgrades:

                p = self.unit.position.rounded
                if 0.0 == self.ai.combat.ground_dps[p]:
                    return self.unit.stop()
                else:
                    retreat_map = self.ai.combat.retreat_ground
                    if retreat_map.dist[p] == np.inf:
                        retreat_point = self.ai.start_location
                    else:
                        retreat_path = retreat_map.get_path(p, 3)
                        retreat_point = Point2(retreat_path[-1]).offset(Point2((0.5, 0.5)))
                    return self.unit.move(retreat_point)

        elif self.unit.health_percentage < 1 / 3 and self.unit.weapon_cooldown and not self.unit.is_revealed:
            return self.unit(AbilityId.BURROWDOWN)

        return None
