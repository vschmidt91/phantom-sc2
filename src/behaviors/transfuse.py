from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from sc2.ids.buff_id import BuffId
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit
from sc2.unit_command import UnitCommand

from ..units.unit import CommandableUnit
from ..constants import ENERGY_COST

if TYPE_CHECKING:
    from ..ai_base import AIBase


class TransfuseBehavior(CommandableUnit):
    ABILITY = AbilityId.TRANSFUSION_TRANSFUSION

    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)

    def priority(self, target: Unit) -> float:
        if self.unit.tag == target.tag:
            return 0
        if not self.unit.in_ability_cast_range(self.ABILITY, target):
            return 0
        if BuffId.TRANSFUSION in target.buffs:
            return 0
        if target.health_max <= target.health + 75:
            return 0
        priority = 1
        priority *= 10 + self.ai.get_unit_value(target)
        priority /= .1 + target.health_percentage
        return priority

    def transfuse(self) -> Optional[UnitCommand]:

        if self.unit.energy < ENERGY_COST[self.ABILITY]:
            return None

        target = max(self.ai.all_own_units,
            key=lambda t: self.priority(t),
            default=None
        )
        if not target:
            return None
        if self.priority(target) <= 0:
            return None

        return self.unit(self.ABILITY, target=target)
