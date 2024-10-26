from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit

from ..action import Action, UseAbility
from ..constants import ENERGY_COST
from .base import Component

if TYPE_CHECKING:
    pass

TRANSFUSE_ABILITY = AbilityId.TRANSFUSION_TRANSFUSION


class TransfuseComponent(Component):

    def do_transfuse(self) -> Iterable[Action]:
        for queen in self.actual_by_type[UnitTypeId.QUEEN]:
            if action := self.do_transfuse_single(queen):
                yield action

    def do_transfuse_single(self, unit: Unit) -> Action | None:

        def priority(target: Unit) -> float:
            if unit.tag == target.tag:
                return 0
            if not unit.in_ability_cast_range(TRANSFUSE_ABILITY, target):
                return 0
            if BuffId.TRANSFUSION in target.buffs:
                return 0
            if target.health_max <= target.health + 75:
                return 0
            priority = 1
            priority *= 10 + self.get_unit_value(target)
            priority /= 0.1 + target.health_percentage
            return priority

        if unit.energy < ENERGY_COST[TRANSFUSE_ABILITY]:
            return None

        target = max(self.all_own_units, key=lambda t: priority(t), default=None)
        if not target:
            return None
        if priority(target) <= 0:
            return None

        return UseAbility(unit, TRANSFUSE_ABILITY, target=target)
