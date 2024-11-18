from sc2.game_state import ActionRawUnitCommand
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit

from bot.common.action import Action, UseAbility
from bot.common.constants import CHANGELINGS, COOLDOWN
from bot.common.main import BotBase

_ABILITY = AbilityId.EFFECT_CORROSIVEBILE


class CorrosiveBiles:
    _bile_last_used = dict[int, int]()

    def handle_action(self, action: ActionRawUnitCommand):
        if action.exact_id == _ABILITY:
            for tag in action.unit_tags:
                self._bile_last_used[tag] = action.game_loop

    def get_action(self, context: BotBase, unit: Unit) -> Action | None:

        def filter_target(t: Unit) -> bool:
            if not context.is_visible(t.position):
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

        last_used = self._bile_last_used.get(unit.tag)
        if last_used is not None:
            if context.state.game_loop < last_used + COOLDOWN[AbilityId.EFFECT_CORROSIVEBILE]:
                return None

        targets = context.all_enemy_units.filter(filter_target)
        if not any(targets):
            return None

        target = max(targets, key=bile_priority)
        return UseAbility(unit, _ABILITY, target=target.position)
