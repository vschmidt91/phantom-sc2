from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger
from sc2.data import ActionResult
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from phantom.common.action import Action
from phantom.common.distribute import distribute
from phantom.common.utils import Point, pairwise_distances

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


class ScoutState:
    def __init__(self, bot: "PhantomBot"):
        self.bot = bot
        self.blocked_positions = dict[Point, float]()
        self.assignment: Mapping[Unit, Point] = dict()
        self.assignment_interval = 17
        self._previous_hash = 0

    def on_step(self, detectors: Units) -> Mapping[Unit, Action]:
        for p, blocked_since in list(self.blocked_positions.items()):
            if blocked_since + 60 < self.bot.time:
                logger.info(f"Resetting blocked base {p}")
                del self.blocked_positions[p]

        for error in self.bot.state.action_errors:
            error_ability = AbilityId(error.ability_id)
            error_result = ActionResult(error.result)
            if (
                error_ability not in {AbilityId.BUILD_CREEPTUMOR_TUMOR, AbilityId.BUILD_CREEPTUMOR_QUEEN}
                and error_result in {ActionResult.CantBuildLocationInvalid, ActionResult.CouldntReachTarget}
                and (unit := self.bot._units_previous_map.get(error.unit_tag))
            ):
                if isinstance(unit.order_target, Point2):
                    p = tuple(unit.order_target.rounded)
                else:
                    p = tuple(unit.position.rounded)
                if p not in self.blocked_positions:
                    self.blocked_positions[p] = self.bot.time
                    logger.info(f"Detected blocked base {p}")

        if self.bot.actual_iteration % self.assignment_interval == 0:
            self._update_assignment(detectors)

        actions = {u: ScoutPosition(Point2(p)) for u, p in self.assignment.items()}
        return actions

    def _update_assignment(self, detectors: Sequence[Unit]) -> None:
        detect_targets = list(self.blocked_positions)
        detectors_limited = sorted(detectors, key=lambda u: u.tag)[: len(detect_targets)]
        assignment_hash = hash(
            (
                frozenset(u.tag for u in detectors_limited),
                frozenset(detect_targets),
            )
        )
        if assignment_hash != self._previous_hash and self.bot.actual_iteration % self.assignment_interval == 0:
            logger.debug("Assigning scout targets")
            self.assignment = distribute(
                detectors_limited[: len(detect_targets)],
                detect_targets,
                pairwise_distances(
                    [u.position for u in detectors_limited],
                    detect_targets,
                ),
            )
            self._previous_hash = assignment_hash
