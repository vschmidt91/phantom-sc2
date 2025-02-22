from dataclasses import dataclass

from loguru import logger
from sc2.data import ActionResult
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from phantom.common.action import Action
from phantom.common.assignment import Assignment
from phantom.common.main import BotBase
from phantom.observation import Observation


@dataclass
class ScoutPosition(Action):
    unit: Unit
    target: Point2

    async def execute(self, bot: BotBase) -> bool:
        if self.unit.distance_to(self.target) < self.unit.radius + self.unit.sight_range:
            if self.unit.is_idle:
                return True
            return self.unit.stop()
        else:
            return self.unit.move(self.target)


@dataclass(frozen=True)
class ScoutAction:
    actions: dict[Unit, ScoutPosition]


class ScoutState:

    blocked_positions = dict[Point2, float]()

    def step(self, observation: Observation) -> ScoutAction:

        for p, blocked_since in list(self.blocked_positions.items()):
            if blocked_since + 60 < observation.time:
                del self.blocked_positions[p]

        for error in observation.action_errors:
            if (
                error.result == ActionResult.CantBuildLocationInvalid.value
                and error.ability_id == AbilityId.ZERGBUILD_HATCHERY.value
            ):
                if unit := observation.unit_by_tag.get(error.unit_tag):
                    p = unit.position.rounded
                    if p not in self.blocked_positions:
                        self.blocked_positions[p] = observation.time
                        logger.info(f"Detected blocked base {p}")

        def filter_base(b: Point2) -> bool:
            if observation.is_visible(b):
                return False
            distance_to_enemy = min(b.distance_to(e) for e in observation.enemy_start_locations)
            if distance_to_enemy < b.distance_to(observation.start_location):
                return False
            return True

        scout_targets = list(filter(filter_base, observation.bases))
        detect_targets = list(self.blocked_positions)

        def cost_fn(u: Unit, p: Point2) -> float:
            return u.distance_to(p)

        detectors = observation.units({UnitTypeId.OVERSEER})
        nondetectors = observation.units({UnitTypeId.OVERLORD})

        scout_actions = Assignment.distribute(nondetectors, scout_targets, cost_fn)
        detect_actions = Assignment.distribute(detectors, detect_targets, cost_fn)
        actions = {u: ScoutPosition(u, p) for u, p in (scout_actions + detect_actions).items()}

        return ScoutAction(actions)
