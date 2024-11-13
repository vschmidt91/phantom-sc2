from dataclasses import dataclass

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit

from bot.common.action import Action, UseAbility
from bot.common.constants import CHANGELINGS, COOLDOWN
from bot.common.main import BotBase


@dataclass(frozen=True)
class CorrosiveBiles:
    _bile_last_used = dict[int, int]()

    def get_action(self, context: BotBase, unit: Unit) -> Action | None:

        ability = AbilityId.EFFECT_CORROSIVEBILE

        def bile_priority(t: Unit) -> float:
            if not t.is_enemy:
                return 0.0
            if not context.is_visible(t.position):
                return 0.0
            if not unit.in_ability_cast_range(ability, t.position):
                return 0.0
            if t.is_hallucination:
                return 0.0
            if t.type_id in CHANGELINGS:
                return 0.0
            priority = 10.0 + max(t.ground_dps, t.air_dps)
            priority /= 100.0 + t.health + t.shield
            priority /= 2.0 + t.movement_speed
            return priority

        if unit.type_id != UnitTypeId.RAVAGER:
            return None

        last_used = self._bile_last_used.get(unit.tag, 0)

        if context.state.game_loop < last_used + COOLDOWN[AbilityId.EFFECT_CORROSIVEBILE]:
            return None

        target = max(
            context.all_enemy_units,
            key=lambda t: bile_priority(t),
            default=None,
        )

        if not target:
            return None

        if bile_priority(target) <= 0:
            return None

        self._bile_last_used[unit.tag] = context.state.game_loop
        return UseAbility(unit, ability, target=target.position)
