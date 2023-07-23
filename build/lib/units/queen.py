from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit, UnitCommand

from src.behaviors.inject import InjectReciever

from ..behaviors.creep import CreepBehavior
from ..behaviors.inject import InjectProvider
from ..behaviors.transfuse import TransfuseBehavior
from ..constants import ENERGY_COST
from ..modules.combat import CombatBehavior
from ..modules.dodge import DodgeBehavior

if TYPE_CHECKING:
    from ..ai_base import AIBase


class Queen(
    DodgeBehavior, InjectProvider, CreepBehavior, TransfuseBehavior, CombatBehavior
):
    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)

    def get_inject_ability(self, reciever: InjectReciever) -> AbilityId:
        return AbilityId.EFFECT_INJECTLARVA

    def can_inject(self) -> bool:
        if self.state.is_burrowed:
            return False
        if self.state.energy < ENERGY_COST[AbilityId.EFFECT_INJECTLARVA]:
            return False
        if 1 < self.ai.combat.ground_dps[self.state.position.rounded]:
            return False
        return True

    def get_command(self) -> Optional[UnitCommand]:
        if command := self.dodge():
            return command
        elif command := self.inject():
            return command
        elif self.ai.combat.ground_dps[self.state.position.rounded] < 1 and (
            command := self.spread_creep()
        ):
            return command
        elif command := self.transfuse():
            return command
        elif command := self.fight():
            return command
        else:
            return None
