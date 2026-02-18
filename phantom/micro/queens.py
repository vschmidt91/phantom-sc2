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
    from phantom.micro.combat import CombatStep


class Queens:
    def __init__(self, bot: PhantomBot, creep: CreepSpread) -> None:
        self.bot = bot
        self.creep = creep
        self._queens = list[Unit]()
        self._inject_targets = list[Unit]()
        self._combat: CombatStep | None = None
        self._should_spread_creep = False

    def on_step(self, observation: Observation) -> None:
        self._queens = list(observation.queens)
        self._inject_targets = list(observation.bot.townhalls.ready if observation.should_inject else [])
        self._combat = observation.combat
        self._should_spread_creep = observation.should_spread_creep

    def get_actions(self, observation: Observation) -> dict[Unit, Action]:
        if self._combat is None:
            return {}
        queens = self._queens
        inject_targets = self._inject_targets
        creep = self.creep if self._should_spread_creep else None
        inject_assignment = (
            distribute(
                inject_targets,
                queens,
                pairwise_distances(
                    [b.position for b in inject_targets],
                    [a.position for a in queens],
                ),
                max_assigned=1,
            )
            if queens and inject_targets
            else {}
        )
        inject_assignment_inverse = {q: h for h, q in inject_assignment.items()}
        return {
            queen: action
            for queen in queens
            if (
                action := self._get_action(
                    queen=queen,
                    inject_target=inject_assignment_inverse.get(queen),
                    creep=creep,
                    combat=self._combat,
                )
            )
        }

    def _get_action(
        self, queen: Unit, inject_target: Unit | None, creep: CreepSpread | None, combat: CombatStep
    ) -> Action | None:
        if not combat.is_unit_safe(queen):
            return combat.fight_with(queen)
        if inject_target and (action := self._inject_with(queen, inject_target)):
            return action
        if (creep and (action := creep.spread_with(queen))) or (action := combat.retreat_to_creep(queen)):
            return action
        return combat.fight_with(queen)

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
