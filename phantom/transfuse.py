from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.unit import Unit

from phantom.common.action import Action, UseAbility
from phantom.common.constants import ENERGY_COST
from phantom.observation import Observation


class TransfuseAction:
    def __init__(self, observation: Observation):
        self.observation = observation
        self.ability = AbilityId.TRANSFUSION_TRANSFUSION
        self.eligible_targets = self.observation.combatants.filter(
            lambda t: t.health + 75 <= t.health_max and BuffId.TRANSFUSION not in t.buffs
        )

    def transfuse_with(self, unit: Unit) -> Action | None:
        if unit.energy < ENERGY_COST[self.ability]:
            return None

        def eligible(t: Unit) -> bool:
            return t.tag != unit.tag and unit.in_ability_cast_range(self.ability, t)

        def priority(t: Unit) -> float:
            return 1 - t.shield_health_percentage

        if target := max(filter(eligible, self.eligible_targets), key=priority, default=None):
            return UseAbility(unit, self.ability, target=target)

        return None
