from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.unit import Unit

from phantom.combat.main import CombatStep
from phantom.common.action import Action, Move, UseAbility
from phantom.common.distribute import distribute
from phantom.common.utils import pairwise_distances

if TYPE_CHECKING:
    from phantom.main import PhantomBot


@dataclass
class ScoutPosition(Action):
    target: Point2

    async def execute(self, unit: Unit) -> bool:
        if unit.distance_to(self.target) < 0.1:
            if unit.is_idle:
                return True
            return unit.stop()
        else:
            return unit.move(self.target)


class Overseers:
    def __init__(self, bot: "PhantomBot"):
        self.bot = bot

    def get_actions(
        self,
        overseers: Sequence[Unit],
        scout_targets: Sequence[Unit],
        detection_targets: Sequence[Point2],
        combat: CombatStep,
    ) -> Mapping[Unit, Action]:
        detection_assignment = (
            distribute(
                detection_targets,
                overseers,
                pairwise_distances(
                    detection_targets,
                    [u.position for u in overseers],
                ),
                max_assigned=1,
            )
            if detection_targets and overseers
            else {}
        )
        detection_assignment_inverse = {u: Point2(p) for p, u in detection_assignment.items()}

        if overseers and scout_targets:
            distance = pairwise_distances(
                [a.position for a in overseers],
                [b.position for b in scout_targets],
            )
            if len(overseers) > 1 and scout_targets:
                second_smallest_distances = np.partition(distance, kth=1, axis=0)[1, :]
                second_smallest_distances = np.minimum(20, second_smallest_distances)
                second_smallest_distances = np.repeat(second_smallest_distances[None, :], len(overseers), axis=0)
                scout_cost = distance - second_smallest_distances
            else:
                scout_cost = distance

            scout_assignment = distribute(overseers, scout_targets, scout_cost)
        else:
            scout_assignment = {}

        actions = {
            overseer: action
            for overseer in overseers
            if (
                action := self._get_action(
                    overseer=overseer,
                    detect_target=detection_assignment_inverse.get(overseer),
                    scout_target=scout_assignment.get(overseer),
                    combat=combat,
                )
            )
        }
        return actions

    def _get_action(
        self, overseer: Unit, detect_target: Point2 | None, scout_target: Unit | None, combat: CombatStep
    ) -> Action | None:
        if action := self._spawn_changeling(overseer):
            return action
        elif not combat.is_unit_safe(overseer):
            return combat.retreat_with(overseer)
        elif detect_target:
            return Move(
                self.bot.mediator.find_path_next_point(
                    start=overseer.position,
                    target=detect_target,
                    grid=self.bot.mediator.get_air_grid,
                    smoothing=True,
                )
            )
        elif scout_target:
            return Move(
                self.bot.mediator.find_path_next_point(
                    start=overseer.position,
                    target=scout_target,
                    grid=self.bot.mediator.get_air_grid,
                    smoothing=True,
                )
            )
        else:
            return None

    def _spawn_changeling(self, overseer: Unit) -> Action | None:
        if self.bot.in_pathing_grid(overseer) and overseer.energy >= 50.0:
            return UseAbility(AbilityId.SPAWNCHANGELING_SPAWNCHANGELING)
        else:
            return None
