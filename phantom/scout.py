from dataclasses import dataclass
from itertools import islice

from loguru import logger
from sc2.bot_ai import BotAI
from sc2.data import ActionResult
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from phantom.common.action import Action
from phantom.common.distribute import distribute
from phantom.common.utils import Point, pairwise_distances
from phantom.knowledge import Knowledge
from phantom.observation import Observation


@dataclass
class ScoutPosition(Action):
    unit: Unit
    target: Point2

    async def execute(self, bot: BotAI) -> bool:
        if self.unit.distance_to(self.target) < 0.1:
            if self.unit.is_idle:
                return True
            return self.unit.stop()
        else:
            return self.unit.move(self.target)


@dataclass(frozen=True)
class ScoutAction:
    actions: dict[Unit, ScoutPosition]


class ScoutState:
    def __init__(self, knowledge: Knowledge):
        self.knowledge = knowledge
        self.blocked_positions = dict[Point, float]()
        self.enemy_natural_scouted = True  # TODO: set back to false when overlords stay safer

    def step(self, observation: Observation, safe_overlord_spots: list[Point2]) -> ScoutAction:
        for p, blocked_since in list(self.blocked_positions.items()):
            if blocked_since + 60 < observation.time:
                del self.blocked_positions[p]

        for error in observation.action_errors:
            if (
                error.result == ActionResult.CantBuildLocationInvalid.value
                and error.ability_id == AbilityId.ZERGBUILD_HATCHERY.value
            ) and (unit := observation.unit_by_tag.get(error.unit_tag)):
                p = tuple(unit.position.rounded)
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
            scout_points.extend(t for p in safe_overlord_spots if filter_base(t := tuple(p.rounded)))
            scout_points.extend(scout_bases)

        scout_targets = list(map(Point2, scout_points))
        detect_targets = list(map(Point2, self.blocked_positions))

        scout_actions = distribute(
            nondetectors,
            scout_targets,
            pairwise_distances(
                [u.position for u in nondetectors],
                scout_targets,
            ),
        )
        detect_actions = distribute(
            detectors,
            detect_targets,
            pairwise_distances(
                [u.position for u in detectors],
                detect_targets,
            ),
        )
        actions = {u: ScoutPosition(u, p) for u, p in (scout_actions | detect_actions).items()}

        return ScoutAction(actions)
