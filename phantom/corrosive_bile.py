from collections.abc import Mapping
from typing import TYPE_CHECKING

from ares import UnitTreeQueryType
from cython_extensions import cy_distance_to
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit

from phantom.common.action import Action, Move, UseAbility
from phantom.common.constants import CHANGELINGS
from phantom.common.cooldown import CooldownTracker
from phantom.common.utils import air_dps_of, ground_dps_of

if TYPE_CHECKING:
    from phantom.main import PhantomBot

type CorrosiveBileAction = Mapping[Unit, Action]


def _target_priority(u: Unit) -> float:
    priority = 10.0 + max(ground_dps_of(u), air_dps_of(u))
    priority /= 100.0 + u.health + u.shield
    priority /= 1.0 + 10 * u.movement_speed
    return priority


class CorrosiveBile:
    def __init__(self, bot: "PhantomBot") -> None:
        self.bot = bot
        self.bile_last_used = dict[int, int]()
        self.ability = AbilityId.EFFECT_CORROSIVEBILE
        self.ability_range = bot.game_data.abilities[self.ability.value]._proto.cast_range
        self.cooldown_tracker = CooldownTracker(bot, self.ability, 160)
        self.bonus_distance = 2.0

    def on_step(self):
        self.cooldown_tracker.on_step()

    def bile_with(self, unit: Unit) -> Action | None:
        if self.cooldown_tracker.get_cooldown(unit):
            return None
        if self.bot.mediator.is_position_safe(grid=self.bot.mediator.get_ground_grid, position=unit.position):
            bonus_distance = self.bonus_distance
        else:
            bonus_distance = 0.0
        (targets,) = self.bot.mediator.get_units_in_range(
            start_points=[unit],
            distances=[unit.radius + self.ability_range + bonus_distance],
            query_tree=UnitTreeQueryType.AllEnemy,
        )
        if not targets:
            return None
        target = max(filter(self._can_be_targeted, targets), key=_target_priority)
        if cy_distance_to(unit.position, target.position) <= unit.radius + self.ability_range:
            return UseAbility(self.ability, target=target.position)
        else:
            return Move(target.position)

    def _can_be_targeted(self, unit: Unit) -> bool:
        return self.bot.is_visible(unit) and not unit.is_hallucination and unit.type_id not in CHANGELINGS
