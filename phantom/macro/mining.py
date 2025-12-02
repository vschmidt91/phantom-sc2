from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from loguru import logger
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from phantom.common.action import Action, Smart
from phantom.common.distribute import get_assignment_solver
from phantom.common.utils import Point, pairwise_distances, to_point

if TYPE_CHECKING:
    from phantom.main import PhantomBot

type HarvesterAssignment = dict[int, Point]


@dataclass
class GatherAction(Action):
    target: Unit
    speedmining_position: Point2

    async def execute(self, unit: Unit) -> bool:
        if unit.order_target != self.target.tag:
            if unit.game_loop < 10:
                return unit.move(self.speedmining_position) and unit.smart(self.target, queue=True)
            else:
                return unit.smart(self.target)
        if 0.75 < unit.distance_to(self.speedmining_position) < 1.75:
            return unit.move(self.speedmining_position) and unit.smart(self.target, queue=True)
        else:
            return True


@dataclass
class ReturnResource(Action):
    return_target: Unit
    speedmining_position: Point2

    async def execute(self, unit: Unit) -> bool:
        move_target = self.speedmining_position
        if 0.75 < unit.position.distance_to(move_target) < 1.5:
            return unit.move(move_target) and unit.smart(self.return_target, queue=True)
        else:
            return True


class MiningContext:
    def __init__(
        self,
        bot: "PhantomBot",
        harvesters: Sequence[Unit],
        mineral_fields: Sequence[Unit],
        gas_buildings: Sequence[Unit],
        gas_target: int,
    ):
        self.bot = bot
        self.harvesters = harvesters
        self.mineral_fields = mineral_fields
        self.gas_buildings = gas_buildings
        self.gas_target = gas_target
        self.resources = list[Unit]()
        self.resources.extend(self.mineral_fields)
        self.resources.extend(self.gas_buildings)
        self.resource_by_position = {to_point(r.position): r for r in self.resources}

        self.gather_hash = hash(
            (
                frozenset(harvesters),
                frozenset(self.mineral_fields),
                frozenset(self.gas_buildings),
                self.bot.harvesters_per_gas_building,
                self.gas_target,
            )
        )


@dataclass
class MiningState:
    bot: "PhantomBot"
    assignment: HarvesterAssignment = field(default_factory=dict)
    gather_hash = 0

    def step(self, observation: MiningContext) -> "MiningStep":
        action = MiningStep(self, observation)
        self.assignment = action.harvester_assignment
        self.gather_hash = observation.gather_hash
        return action


class MiningStep:
    def __init__(
        self,
        state: MiningState,
        context: MiningContext,
    ):
        self.state = state
        self.context = context
        self.harvester_assignment = self._harvester_assignment()

    def _harvester_assignment(self) -> HarvesterAssignment:
        if self.context.gather_hash == self.state.gather_hash:
            return self.state.assignment
        elif (solution := self.solve()) is not None:
            return solution
        else:
            logger.error("Harvester assignment solve failed")
            return self.state.assignment

    def solve(self) -> HarvesterAssignment | None:
        harvesters = self.context.harvesters

        resources = list[Unit]()
        resources.extend(self.context.mineral_fields)
        resources.extend(self.context.gas_buildings)
        mineral_limits = len(self.context.mineral_fields) * [self.context.bot.harvesters_per_mineral_field]
        gas_limits = len(self.context.gas_buildings) * [self.context.bot.harvesters_per_gas_building]
        resource_limit = [*mineral_limits, *gas_limits]

        if not any(resources):
            return {}

        mineral_max = sum(mineral_limits)
        gas_max = sum(gas_limits)

        gas_target = min(gas_max, self.context.gas_target)

        harvester_max = mineral_max + gas_target
        if harvester_max < len(harvesters):
            harvesters = sorted(harvesters, key=lambda u: u.tag)[:harvester_max]

        if not any(harvesters):
            return {}

        harvester_to_resource = pairwise_distances(
            [h.position for h in harvesters],
            [self.state.bot.gather_targets[to_point(r.position)] for r in resources],
        )

        return_distance = np.array([self.state.bot.return_distances[to_point(r.position)] for r in resources])
        return_distance = np.repeat(return_distance[None, ...], len(harvesters), axis=0)

        assignment_cost = np.ones((len(harvesters), len(resources)))
        resource_index_by_position = {to_point(r.position): i for i, r in enumerate(resources)}
        for i, hi in enumerate(harvesters):
            if (ti := self.state.assignment.get(hi.tag)) and (j := resource_index_by_position.get(ti)) is not None:
                assignment_cost[i, j] = 0.0

        n = len(harvesters)
        m = len(resources)

        cost = harvester_to_resource + 5 * return_distance + assignment_cost
        is_gas = np.array([1.0 if r.mineral_contents == 0 else 0.0 for r in resources])
        limit = np.array(resource_limit)

        problem = get_assignment_solver(n, m)
        problem.set_total(is_gas, gas_target)

        x = problem.solve(cost, limit)
        indices = x.argmax(axis=1)
        assignment = {
            ai.tag: to_point(resources[j].position) for (i, ai), j in zip(enumerate(harvesters), indices, strict=False)
        }

        return assignment

    def gather_with(self, unit: Unit, return_targets: Units) -> Action | None:
        if not (target_pos := self.harvester_assignment.get(unit.tag)):
            return None
        if not (target := self.context.resource_by_position.get(target_pos)):
            logger.error(f"No resource found at {target_pos}")
            return None
        elif len(unit.orders) >= 2:
            return None
        elif unit.is_gathering:
            return GatherAction(target, self.state.bot.gather_targets[target_pos])
        elif unit.is_returning:
            if not any(return_targets):
                return None
            return_target = min(return_targets, key=lambda th: th.distance_to(unit))
            return_point = self.state.bot.return_targets[target_pos]
            return ReturnResource(return_target, return_point)
        return Smart(target)
