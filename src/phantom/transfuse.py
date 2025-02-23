from dataclasses import dataclass
from functools import cached_property
from typing import Iterable

from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.unit import Unit
from sc2.units import Units

from phantom.observation import Observation
from phantom.common.action import Action, UseAbility
from phantom.common.constants import ENERGY_COST


@dataclass(frozen=True)
class TransfuseAction:
    observation: Observation
    ability = AbilityId.TRANSFUSION_TRANSFUSION

    @cached_property
    def eligible_targets(self) -> Units:
        def eligible(t: Unit) -> bool:
            return (
                t.health + 75 <= t.health_max
                and BuffId.TRANSFUSION not in t.buffs
            )
        return self.observation.combatants.filter(eligible)

    def transfuse_with(self, unit: Unit) -> Action | None:

        if unit.energy < ENERGY_COST[self.ability]:
            return None

        def eligible(t: Unit) -> bool:
            return (
                t.tag != unit.tag
                and unit.in_ability_cast_range(self.ability, t)
            )

        def priority(t: Unit) -> float:
            return 1 - t.shield_health_percentage

        if target := max(filter(eligible, self.eligible_targets), key=priority, default=None):
            return UseAbility(unit, self.ability, target=target)

        return None
