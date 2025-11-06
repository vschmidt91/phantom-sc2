from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from loguru import logger
from sc2.data import ActionResult
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from phantom.common.action import Action
from phantom.common.distribute import distribute
from phantom.common.utils import Point, pairwise_distances
from phantom.knowledge import Knowledge
from phantom.observation import Observation


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


type ScoutAction = Mapping[Unit, Action]


class ScoutState:
    def __init__(self, knowledge: Knowledge):
        self.knowledge = knowledge
        self.blocked_positions = dict[Point, float]()
        self._previous_hash = 0
        self.assignment: Mapping[Unit, Point] = dict()

    def _assign(self, detectors: Units, detect_targets: Sequence[Point]) -> Mapping[Unit, Point]:
        logger.debug("Assigning scout targets")
        detect_assignment = distribute(
            detectors,
            detect_targets,
            pairwise_distances(
                [u.position for u in detectors],
                detect_targets,
            ),
            max_assigned=1,
        )
        return detect_assignment

    def step(self, observation: Observation, detectors: Units) -> ScoutAction:
        # TODO
        if len(self.blocked_positions) > 100:
            logger.error("Too many blocked positions, resetting")
            observation.bot.add_replay_tag("blocked_positions_reset")  # type: ignore
            self.blocked_positions = dict()

        for p, blocked_since in list(self.blocked_positions.items()):
            if blocked_since + 60 < observation.time:
                logger.info(f"Resetting blocked base {p}")
                del self.blocked_positions[p]

        for error in observation.action_errors:
            error_ability = AbilityId(error.ability_id)
            error_result = ActionResult(error.result)
            if (
                error_ability not in {AbilityId.BUILD_CREEPTUMOR_TUMOR, AbilityId.BUILD_CREEPTUMOR_QUEEN}
                and error_result in {ActionResult.CantBuildLocationInvalid, ActionResult.CouldntReachTarget}
                and (unit := observation.bot._units_previous_map.get(error.unit_tag))
            ):
                if isinstance(unit.order_target, Point2):
                    p = tuple(unit.order_target.rounded)
                else:
                    p = tuple(unit.position.rounded)
                if p not in self.blocked_positions:
                    self.blocked_positions[p] = observation.time
                    logger.info(f"Detected blocked base {p}")

        detect_targets = list(self.blocked_positions)

        assignment_hash = hash(
            (
                frozenset(u.tag for u in detectors),
                frozenset(detect_targets),
            )
        )
        if assignment_hash != self._previous_hash and observation.iteration % 17 == 0:
            self.assignment = self._assign(detectors, detect_targets)
            self._previous_hash = assignment_hash
        assignment = self.assignment

        actions = {u: ScoutPosition(Point2(p)) for u, p in assignment.items()}
        return actions
