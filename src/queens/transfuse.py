from typing import Iterable

from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.unit import Unit

from src.common.action import Action, UseAbility
from src.common.constants import ENERGY_COST

TRANSFUSE_ABILITY = AbilityId.TRANSFUSION_TRANSFUSION


def transfuse_with(unit: Unit, targets: Iterable[Unit]) -> Action | None:

    if unit.energy < ENERGY_COST[TRANSFUSE_ABILITY]:
        return None

    eligible_targets = [
        t
        for t in targets
        if (
            t.tag != unit.tag
            and unit.in_ability_cast_range(TRANSFUSE_ABILITY, t)
            and BuffId.TRANSFUSION not in t.buffs
            and t.health + 75 <= t.health_max
        )
    ]

    if not any(eligible_targets):
        return None

    target = min(eligible_targets, key=lambda t: t.health_percentage, default=None)
    return UseAbility(unit, TRANSFUSE_ABILITY, target=target)
