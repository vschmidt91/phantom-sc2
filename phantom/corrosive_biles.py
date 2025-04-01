from dataclasses import dataclass

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit

from phantom.common.action import Action, UseAbility
from phantom.common.constants import CHANGELINGS, COOLDOWN
from phantom.observation import Observation

_ABILITY = AbilityId.EFFECT_CORROSIVEBILE


@dataclass(frozen=True)
class CorrosiveBileAction:
    actions: dict[Unit, Action]


class CorrosiveBileState:
    def __init__(self) -> None:
        self.bile_last_used = dict[int, int]()

    def step(self, obs: Observation) -> CorrosiveBileAction:
        ravagers = obs.combatants({UnitTypeId.RAVAGER})
        for ravager in ravagers:
            if (action := obs.unit_commands.get(ravager.tag)) and action.exact_id == _ABILITY:
                self.bile_last_used[ravager.tag] = action.game_loop

        actions = {r: a for r in ravagers if (a := self.step_unit(obs, r))}
        return CorrosiveBileAction(actions)

    def step_unit(self, obs: Observation, unit: Unit) -> Action | None:
        def filter_target(t: Unit) -> bool:
            return not (
                not obs.is_visible(t)
                or not unit.in_ability_cast_range(_ABILITY, t.position)
                or t.is_hallucination
                or t.type_id in CHANGELINGS
            )

        def bile_priority(t: Unit) -> float:
            priority = 10.0 + max(t.ground_dps, t.air_dps)
            priority /= 100.0 + t.health + t.shield
            priority /= 2.0 + t.movement_speed
            return priority

        last_used = self.bile_last_used.get(unit.tag)
        if last_used is not None and obs.game_loop < last_used + COOLDOWN[AbilityId.EFFECT_CORROSIVEBILE]:
            return None

        targets = obs.enemy_units.filter(filter_target)
        if not any(targets):
            return None

        target = max(targets, key=bile_priority)
        return UseAbility(unit, _ABILITY, target=target.position)
