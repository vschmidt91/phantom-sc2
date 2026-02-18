from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.unit import Unit

from phantom.common.action import Action, Move, UseAbility
from phantom.common.distribute import distribute
from phantom.common.utils import pairwise_distances
from phantom.observation import Observation

if TYPE_CHECKING:
    from phantom.main import PhantomBot
    from phantom.micro.combat import CombatSituation


class Overseers:
    def __init__(self, bot: PhantomBot):
        self.bot = bot
        self._overseers = list[Unit]()
        self._scout_targets = list[Unit]()
        self._detection_targets = list[Point2]()
        self._situation: CombatSituation | None = None
        self._detect_target_by_overseer_tag = dict[int, Point2]()
        self._scout_target_by_overseer_tag = dict[int, Unit]()

    def target_cost(self, target: Unit) -> float:
        is_detected = self.bot.mediator.get_is_detected(unit=target, by_enemy=target.is_mine)
        if (target.is_cloaked or target.is_burrowed) and not is_detected:
            return 0.1
        return 1

    def on_step(self, observation: Observation) -> None:
        self._overseers = list(observation.overseers)
        self._scout_targets = list(observation.enemy_combatants or observation.bot.all_enemy_units)
        self._detection_targets = list(observation.detection_targets)
        self._situation = observation.combat
        detection_assignment = (
            distribute(
                self._detection_targets,
                self._overseers,
                pairwise_distances(
                    self._detection_targets,
                    [u.position for u in self._overseers],
                ),
                max_assigned=1,
            )
            if self._detection_targets and self._overseers
            else {}
        )
        detection_assignment_inverse = {u: Point2(p) for p, u in detection_assignment.items()}
        self._detect_target_by_overseer_tag = {
            overseer.tag: target for overseer, target in detection_assignment_inverse.items()
        }

        if self._overseers and self._scout_targets:
            distance = pairwise_distances(
                [a.position for a in self._overseers],
                [b.position for b in self._scout_targets],
            )
            scout_cost = distance
            if len(self._overseers) > 1 and self._scout_targets:
                second_smallest_distances = np.partition(distance, kth=1, axis=0)[1, :]
                second_smallest_distances = np.minimum(20, second_smallest_distances)
                scout_cost = scout_cost - second_smallest_distances[None, :]

            target_costs = np.array(list(map(self.target_cost, self._scout_targets)))
            scout_cost = scout_cost * target_costs[None, :]
            scout_assignment = distribute(self._overseers, self._scout_targets, scout_cost)
        else:
            scout_assignment = {}
        self._scout_target_by_overseer_tag = {overseer.tag: target for overseer, target in scout_assignment.items()}

    def overseers_to_micro(self) -> list[Unit]:
        return self._overseers

    def get_action(self, overseer: Unit) -> Action | None:
        if self._situation is None:
            return None
        return self._get_action(
            overseer=overseer,
            detect_target=self._detect_target_by_overseer_tag.get(overseer.tag),
            scout_target=self._scout_target_by_overseer_tag.get(overseer.tag),
            situation=self._situation,
        )

    def _get_action(
        self, overseer: Unit, detect_target: Point2 | None, scout_target: Unit | None, situation: CombatSituation | None
    ) -> Action | None:
        if situation is None:
            return None
        if (action := self._spawn_changeling(overseer)) or (action := situation.keep_unit_safe(overseer)):
            return action
        if detect_target:
            return Move(
                self.bot.mediator.find_path_next_point(
                    start=overseer.position,
                    target=detect_target,
                    grid=self.bot.mediator.get_air_grid,
                    smoothing=True,
                )
            )
        if scout_target:
            return Move(
                self.bot.mediator.find_path_next_point(
                    start=overseer.position,
                    target=scout_target.position,
                    grid=self.bot.mediator.get_air_grid,
                    smoothing=True,
                )
            )
        return None

    def _spawn_changeling(self, overseer: Unit) -> Action | None:
        if self.bot.in_pathing_grid(overseer) and overseer.energy >= 50.0:
            return UseAbility(AbilityId.SPAWNCHANGELING_SPAWNCHANGELING)
        return None
