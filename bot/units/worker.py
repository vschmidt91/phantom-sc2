from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sc2.ids.ability_id import AbilityId
from sc2.ids.upgrade_id import UpgradeId
from sc2.unit import Unit, UnitCommand

from ..modules.combat import CombatBehavior
from ..modules.dodge import DodgeBehavior

if TYPE_CHECKING:
    from ..ai_base import PhantomBot


class Worker(DodgeBehavior, CombatBehavior):
    def __init__(self, ai: PhantomBot, unit: Unit):
        super().__init__(ai, unit)
        self.is_drafted: bool = False

    def get_command(self) -> Optional[UnitCommand]:
        if command := self.dodge():
            return command
        elif self.is_drafted:
            return self.fight()
        elif 1 < self.ai.combat.ground_dps[self.unit.position.rounded] and UpgradeId.BURROW in self.ai.state.upgrades:
            return self.unit(AbilityId.BURROWDOWN)
            # else:
            #     return self.fight()
        elif self.unit.is_burrowed:
            return self.unit(AbilityId.BURROWUP)
        else:
            return None
        # return self.dodge() or self.fight() or self.macro() or self.gather()
