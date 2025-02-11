from dataclasses import dataclass

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit

from bot.common.action import Action, UseAbility
from bot.common.constants import CHANGELINGS, COOLDOWN
from bot.common.observation import Observation

_ABILITY = AbilityId.EFFECT_CORROSIVEBILE


@dataclass(frozen=True)
class CorrosiveBileAction:
    actions: dict[Unit, Action]


class CorrosiveBile:

    bile_last_used = dict[int, int]()

    def step(self, obs: Observation) -> CorrosiveBileAction:
        ravagers = obs.units({UnitTypeId.RAVAGER})
        for ravager in ravagers:
            if action := obs.unit_commands.get(ravager.tag):
                if action.exact_id == _ABILITY:
                    self.bile_last_used[ravager.tag] = action.game_loop

        actions = {r: a for r in ravagers if (a := self.step_unit(obs, r))}
        return CorrosiveBileAction(actions)

    def step_unit(self, obs: Observation, unit: Unit) -> Action | None:

        def filter_target(t: Unit) -> bool:
            if not obs.bot.is_visible(t.position):
                return False
            elif not unit.in_ability_cast_range(_ABILITY, t.position):
                return False
            elif t.is_hallucination:
                return False
            elif t.type_id in CHANGELINGS:
                return False
            return True

        def bile_priority(t: Unit) -> float:
            priority = 10.0 + max(t.ground_dps, t.air_dps)
            priority /= 100.0 + t.health + t.shield
            priority /= 2.0 + t.movement_speed
            return priority

        last_used = self.bile_last_used.get(unit.tag)
        if last_used is not None:
            if obs.game_loop < last_used + COOLDOWN[AbilityId.EFFECT_CORROSIVEBILE]:
                return None

        targets = obs.bot.all_enemy_units.filter(filter_target)
        if not any(targets):
            return None

        target = max(targets, key=bile_priority)
        return UseAbility(unit, _ABILITY, target=target.position)
