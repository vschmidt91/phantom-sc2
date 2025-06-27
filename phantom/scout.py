from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import islice

from loguru import logger
from sc2.data import ActionResult
from sc2.ids.unit_typeid import UnitTypeId
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
        self.enemy_natural_scouted = True  # TODO: set back to false when overlords stay safer
        self._previous_hash = 0
        self.assignment: Mapping[Unit, Point2] = dict()

    def _assign(
        self, nondetectors: Units, scout_targets: Sequence[Point2], detectors: Units, detect_targets: Sequence[Point2]
    ) -> Mapping[Unit, Point2]:
        logger.debug("Assigning scout targets")
        scout_assignment = distribute(
            nondetectors,
            scout_targets,
            pairwise_distances(
                [u.position for u in nondetectors],
                scout_targets,
            ),
            max_assigned=1,
        )
        detect_assignment = distribute(
            detectors,
            detect_targets,
            pairwise_distances(
                [u.position for u in detectors],
                detect_targets,
            ),
            max_assigned=1,
        )
        assignment = {**scout_assignment, **detect_assignment}
        return assignment

    def step(self, observation: Observation, safe_overlord_spots: list[Point2]) -> ScoutAction:
        for p, blocked_since in list(self.blocked_positions.items()):
            if blocked_since + 60 < observation.time:
                logger.info(f"Resetting blocked base {p}")
                del self.blocked_positions[p]

        for error in observation.action_errors:
            # error_ability = AbilityId(error.ability_id)
            error_result = ActionResult(error.result)
            if (
                error_result in {ActionResult.CantBuildLocationInvalid, ActionResult.CouldntReachTarget}
                and (unit := observation.bot._units_previous_map.get(error.unit_tag))
                and isinstance(unit.order_target, Point2)
            ):
                p = tuple(unit.order_target.rounded)
                if p not in self.blocked_positions:
                    self.blocked_positions[p] = observation.time
                    logger.info(f"Detected blocked base {p}")

        def filter_base(b: Point2) -> bool:
            if observation.is_visible[b]:
                return False
            distance_to_enemy = min(b.distance_to(Point2(e)) for e in self.knowledge.enemy_start_locations)
            return distance_to_enemy > b.distance_to(observation.start_location)

        detectors = observation.units({UnitTypeId.OVERSEER})
        nondetectors = observation.units({UnitTypeId.OVERLORD})

        scout_points = list[Point]()
        scout_bases = filter(filter_base, self.knowledge.bases)
        if not self.knowledge.is_micro_map and not self.enemy_natural_scouted and observation.enemy_natural:
            if observation.is_visible[observation.enemy_natural]:
                self.enemy_natural_scouted = True
            else:
                scout_points.append(tuple(observation.enemy_natural.rounded))
            scout_points.extend(islice(scout_bases, len(nondetectors) - len(scout_points)))
        else:
            if not self.knowledge.is_micro_map:
                scout_points.extend(tuple(pr) for p in safe_overlord_spots if filter_base(pr := p.rounded))
            scout_points.extend(scout_bases)

        scout_targets = list(map(Point2, scout_points))
        detect_targets = list(map(Point2, self.blocked_positions))

        assignment_hash = hash(
            (
                frozenset(u.tag for u in nondetectors),
                frozenset(u.tag for u in detectors),
                frozenset(scout_targets),
                frozenset(detect_targets),
            )
        )
        if assignment_hash != self._previous_hash and observation.iteration % 17 == 0:
            self.assignment = self._assign(nondetectors, scout_targets, detectors, detect_targets)
            self._previous_hash = assignment_hash
        assignment = self.assignment

        actions = {u: ScoutPosition(p) for u, p in assignment.items()}
        return actions
