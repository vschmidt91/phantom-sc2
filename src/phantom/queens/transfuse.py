from typing import Iterable

from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.unit import Unit

from phantom.common.action import Action, UseAbility
from phantom.common.constants import ENERGY_COST

TRANSFUSE_ABILITY = AbilityId.TRANSFUSION_TRANSFUSION


def transfuse_with(unit: Unit, targets: Iterable[Unit]) -> Action | None:

    if unit.energy < ENERGY_COST[TRANSFUSE_ABILITY]:
        return None

    def eligible(t: Unit) -> bool:
        return (
            t.health + 75 <= t.health_max
            and BuffId.TRANSFUSION not in t.buffs
            and t.tag != unit.tag
            and unit.in_ability_cast_range(TRANSFUSE_ABILITY, t)
        )

    if target := min(filter(eligible, targets), key=lambda t: t.health_percentage, default=None):
        return UseAbility(unit, TRANSFUSE_ABILITY, target=target)

    return None
