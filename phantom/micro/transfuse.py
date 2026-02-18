from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from ares import UnitTreeQueryType
from cython_extensions import cy_distance_to
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit

from phantom.common.action import Action, Move, UseAbility
from phantom.observation import Observation

if TYPE_CHECKING:
    from phantom.main import PhantomBot


class Transfuse:
    def __init__(self, bot: PhantomBot):
        self.bot = bot
        self.ability = AbilityId.TRANSFUSION_TRANSFUSION
        self.ability_range = bot.game_data.abilities[self.ability.value]._proto.cast_range
        self.ability_energy_cost = 50
        self.min_wounded = 75
        self.bonus_distance = 2.0
        self.transfuse_structures = {UnitTypeId.SPINECRAWLER, UnitTypeId.SPORECRAWLER}
        self._transfused_this_step = set[int]()
        self._queens = list[Unit]()

    def on_step(self, observation: Observation | None = None) -> None:
        self._transfused_this_step.clear()
        if observation is not None:
            self._queens = list(observation.queens)

    def get_actions(self, observation: Observation) -> Mapping[Unit, Action]:
        return {queen: action for queen in self._queens if (action := self.transfuse_with(queen))}

    def transfuse_with(self, unit: Unit) -> Action | None:
        if unit.energy < self.ability_energy_cost:
            return None

        is_safe_on_creep = self.bot.mediator.is_position_safe(
            grid=self.bot.ground_grid, position=unit.position
        ) and self.bot.has_creep(unit)
        bonus_distance = self.bonus_distance if is_safe_on_creep else 0.0

        (targets,) = self.bot.mediator.get_units_in_range(
            start_points=[unit],
            distances=[unit.radius + self.ability_range + bonus_distance],
            query_tree=UnitTreeQueryType.AllOwn,
        )

        def is_eligible(t: Unit) -> bool:
            return (
                t != unit
                and t.tag not in self._transfused_this_step
                and t.health + self.min_wounded <= t.health_max
                and (not t.is_structure or t.type_id in self.transfuse_structures)
            )

        def priority(t: Unit) -> float:
            return 1 - t.shield_health_percentage

        if target := max(filter(is_eligible, targets), key=priority, default=None):
            if cy_distance_to(unit.position, target.position) <= unit.radius + self.ability_range:
                self._transfused_this_step.add(target.tag)
                return UseAbility(self.ability, target=target)
            return Move(target.position)

        return None
