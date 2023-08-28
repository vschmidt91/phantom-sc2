from __future__ import annotations

from typing import Optional

from sc2.ids.ability_id import AbilityId
from sc2.unit import UnitCommand

from src.behaviors.inject import InjectReciever

from ..behaviors.creep import CreepBehavior
from ..behaviors.inject import InjectProvider
from ..behaviors.transfuse import TransfuseBehavior
from ..constants import ENERGY_COST
from ..modules.combat import CombatBehavior
from ..modules.dodge import DodgeBehavior
from .unit import AIUnit


class Queen(
    DodgeBehavior, InjectProvider, CreepBehavior, TransfuseBehavior, CombatBehavior
):
    def __init__(self, unit: AIUnit) -> None:
        super().__init__(unit)

    def get_inject_ability(self, reciever: InjectReciever) -> AbilityId:
        return AbilityId.EFFECT_INJECTLARVA

    def can_inject(self) -> bool:
        if self.unit.state.is_burrowed:
            return False
        if self.unit.state.energy < ENERGY_COST[AbilityId.EFFECT_INJECTLARVA]:
            return False
        if 1 < self.ai.combat.ground_dps[self.unit.state.position.rounded]:
            return False
        return True

    def wants_to_fight(self) -> bool:
        if not self.ai.has_creep(self.unit.state.position):
            return False
        return super().wants_to_fight()

    def get_command(self) -> Optional[UnitCommand]:
        if command := self.dodge():
            return command
        elif command := self.inject():
            return command
        elif self.ai.combat.ground_dps[self.unit.state.position.rounded] < 1 and (
            command := self.spread_creep()
        ):
            return command
        elif command := self.transfuse():
            return command
        elif command := self.fight():
            return command
        else:
            return None
