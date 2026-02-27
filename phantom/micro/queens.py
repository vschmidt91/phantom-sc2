from __future__ import annotations

from typing import TYPE_CHECKING

from cython_extensions import cy_distance_to
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit

from phantom.common.action import Action, Move, UseAbility
from phantom.common.constants import ENERGY_GENERATION_RATE
from phantom.common.distribute import distribute
from phantom.common.utils import pairwise_distances
from phantom.micro.creep import CreepSpread
from phantom.observation import Observation

if TYPE_CHECKING:
    from phantom.main import PhantomBot
    from phantom.micro.combat import CombatSituation


class Queens:
    def __init__(self, bot: PhantomBot, creep: CreepSpread) -> None:
        self.bot = bot
        self.creep = creep
        self._queens = list[Unit]()
        self._inject_targets = list[Unit]()
        self._situation: CombatSituation | None = None
        self._should_spread_creep = False
        self._inject_target_by_queen_tag = dict[int, Unit]()

    def on_step(self, observation: Observation) -> None:
        self._queens = list(observation.queens)
        self._inject_targets = list(observation.bot.townhalls.ready if observation.should_inject else [])
        self._situation = observation.combat
        self._should_spread_creep = observation.should_spread_creep
        inject_assignment = (
            distribute(
                self._inject_targets,
                self._queens,
                pairwise_distances(
                    [b.position for b in self._inject_targets],
                    [a.position for a in self._queens],
                ),
                max_assigned=1,
            )
            if self._queens and self._inject_targets
            else {}
        )
        self._inject_target_by_queen_tag = {queen.tag: hatch for hatch, queen in inject_assignment.items()}

    def queens_to_micro(self) -> list[Unit]:
        return self._queens

    def get_action(self, queen: Unit) -> Action | None:
        if self._situation is None:
            return None
        creep = self.creep if self._should_spread_creep else None
        return self._get_action(
            queen=queen,
            inject_target=self._inject_target_by_queen_tag.get(queen.tag),
            creep=creep,
            situation=self._situation,
        )

    def _get_action(
        self, queen: Unit, inject_target: Unit | None, creep: CreepSpread | None, situation: CombatSituation
    ) -> Action | None:
        if not situation.is_unit_safe(queen):
            return situation.fight_with(queen) or situation.retreat_with(queen)
        if inject_target and (action := self._inject_with(queen, inject_target)):
            return action
        if (creep and (action := creep.get_action(queen))) or (action := situation.retreat_to_creep(queen)):
            return action
        return situation.fight_with(queen)

    def _inject_with(self, queen: Unit, hatch: Unit) -> Action | None:
        distance = cy_distance_to(queen.position, hatch.position) - queen.radius - hatch.radius
        time_to_reach_target = distance / (1.4 * queen.real_speed)
        time_until_buff_runs_out = hatch.buff_duration_remain / 22.4
        time_to_generate_energy = max(0.0, 25 - queen.energy) / (22.4 * ENERGY_GENERATION_RATE)
        time_until_order = max(time_until_buff_runs_out, time_to_generate_energy)
        if time_until_order == 0:
            return UseAbility(AbilityId.EFFECT_INJECTLARVA, target=hatch)
        elif time_until_order < time_to_reach_target:
            return Move(hatch.position)
        else:
            return None
