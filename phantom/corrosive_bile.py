from collections.abc import Mapping

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit

from phantom.common.action import Action, UseAbility
from phantom.common.constants import CHANGELINGS, COOLDOWN
from phantom.observation import Observation

type CorrosiveBileAction = Mapping[Unit, Action]


class CorrosiveBile:
    def __init__(self) -> None:
        self.bile_last_used = dict[int, int]()
        self.ability = AbilityId.EFFECT_CORROSIVEBILE

    def step(self, obs: Observation) -> CorrosiveBileAction:
        ravagers = obs.combatants(UnitTypeId.RAVAGER)
        for ravager in ravagers:
            if (action := obs.unit_commands.get(ravager.tag)) and action.exact_id == self.ability:
                self.bile_last_used[ravager.tag] = action.game_loop

        actions = {r: a for r in ravagers if (a := self._bile_with(obs, r))}
        return actions

    def _bile_with(self, obs: Observation, unit: Unit) -> Action | None:
        def filter_target(t: Unit) -> bool:
            return (
                obs.is_visible[t.position.rounded]
                and unit.in_ability_cast_range(self.ability, t.position)
                and not t.is_hallucination
                and t.type_id not in CHANGELINGS
            )

        def bile_priority(t: Unit) -> float:
            priority = 10.0 + max(t.ground_dps, t.air_dps)
            priority /= 100.0 + t.health + t.shield
            priority /= 1.0 + 10 * t.movement_speed
            return priority

        last_used = self.bile_last_used.get(unit.tag)
        if last_used is not None and obs.game_loop < last_used + COOLDOWN[AbilityId.EFFECT_CORROSIVEBILE]:
            return None

        targets = obs.enemy_units.filter(filter_target)
        if not any(targets):
            return None

        target = max(targets, key=bile_priority)
        return UseAbility(self.ability, target=target.position)
