from __future__ import annotations

from typing import TYPE_CHECKING

from ares import UnitTreeQueryType
from cython_extensions import cy_distance_to
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit

from phantom.common.action import Action, Move, UseAbility
from phantom.common.constants import CHANGELINGS
from phantom.common.utils import air_dps_of, ground_dps_of
from phantom.observation import Observation

if TYPE_CHECKING:
    from phantom.main import PhantomBot


def _target_priority(u: Unit) -> float:
    priority = 10.0 + max(ground_dps_of(u), air_dps_of(u))
    priority /= 100.0 + u.health + u.shield
    priority /= 1.0 + 10 * u.movement_speed
    return priority


class CorrosiveBile:
    def __init__(self, bot: PhantomBot) -> None:
        self.bot = bot
        self.ability = AbilityId.EFFECT_CORROSIVEBILE
        self.ability_range = bot.game_data.abilities[self.ability.value]._proto.cast_range
        self.bonus_distance = 2.0
        self._ravagers = list[Unit]()

    def on_step(self, observation: Observation) -> None:
        self._ravagers = list(observation.bot.units(UnitTypeId.RAVAGER))

    def ravagers_to_micro(self) -> list[Unit]:
        return self._ravagers

    def get_action(self, unit: Unit) -> Action | None:
        return self.bile_with(unit)

    def bile_with(self, unit: Unit) -> Action | None:
        if self.ability not in unit.abilities:
            return None
        if self.bot.mediator.is_position_safe(grid=self.bot.ground_grid, position=unit.position):
            bonus_distance = self.bonus_distance
        else:
            bonus_distance = 0.0
        (targets,) = self.bot.mediator.get_units_in_range(
            start_points=[unit],
            distances=[unit.radius + self.ability_range + bonus_distance],
            query_tree=UnitTreeQueryType.AllEnemy,
        )
        if target := max(filter(self._can_be_targeted, targets), key=_target_priority, default=None):
            if cy_distance_to(unit.position, target.position) <= unit.radius + self.ability_range:
                return UseAbility(self.ability, target=target.position)
            else:
                return Move(target.position)
        return None

    def _can_be_targeted(self, unit: Unit) -> bool:
        return self.bot.is_visible(unit) and not unit.is_hallucination and unit.type_id not in CHANGELINGS
