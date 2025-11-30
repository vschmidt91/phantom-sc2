from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from loguru import logger
from sc2.unit import Unit
from sc2.units import Units

from phantom.common.action import Action, Smart
from phantom.common.distribute import get_assignment_solver
from phantom.common.utils import pairwise_distances, to_point
from phantom.resources.gather import GatherAction, ReturnResource
from phantom.resources.observation import HarvesterAssignment, ResourceObservation

if TYPE_CHECKING:
    from phantom.main import PhantomBot


@dataclass
class ResourceState:
    bot: "PhantomBot"
    assignment: HarvesterAssignment = field(default_factory=dict)
    gather_hash = 0

    def step(self, observation: ResourceObservation) -> "ResourceAction":
        action = ResourceAction(self, observation)
        self.assignment = action.harvester_assignment
        self.gather_hash = observation.gather_hash
        return action


class ResourceAction:
    def __init__(
        self,
        state: ResourceState,
        observation: ResourceObservation,
    ):
        self.state = state
        self.observation = observation
        self.harvester_assignment = self._harvester_assignment()

    def _harvester_assignment(self) -> HarvesterAssignment:
        if self.observation.gather_hash == self.state.gather_hash:
            return self.state.assignment
        elif (solution := self.solve()) is not None:
            return solution
        else:
            logger.error("Harvester assignment solve failed")
            return self.state.assignment

    def solve(self) -> HarvesterAssignment | None:
        harvesters = self.observation.harvesters

        resources = list[Unit]()
        resources.extend(self.observation.mineral_fields)
        resources.extend(self.observation.gas_buildings)
        mineral_limits = len(self.observation.mineral_fields) * [self.observation.bot.harvesters_per_mineral_field]
        gas_limits = len(self.observation.gas_buildings) * [self.observation.bot.harvesters_per_gas_building]
        resource_limit = [*mineral_limits, *gas_limits]

        if not any(resources):
            return {}

        mineral_max = sum(mineral_limits)
        gas_max = sum(gas_limits)

        gas_target = min(gas_max, self.observation.gas_target)

        harvester_max = mineral_max + gas_target
        if harvester_max < len(harvesters):
            harvesters = sorted(harvesters, key=lambda u: u.tag)[:harvester_max]

        if not any(harvesters):
            return {}

        harvester_to_resource = pairwise_distances(
            [h.position for h in harvesters],
            [self.state.bot.speedmining_positions[to_point(r.position)] for r in resources],
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
            ai.tag: to_point(resources[j].position)
            for (i, ai), j in zip(enumerate(harvesters), indices, strict=False)
            # if x[i, j] > 0
        }

        return assignment

    def gather_with(self, unit: Unit, return_targets: Units) -> Action | None:
        if not (target_pos := self.harvester_assignment.get(unit.tag)):
            return None
        if not (target := self.observation.resource_by_position.get(target_pos)):
            logger.error(f"No resource found at {target_pos}")
            return None
        # if target.is_vespene_geyser and not (target := self.observation.gas_building_at.get(target_pos)):
        #     logger.error(f"No gas building found at {target_pos}")
        #     return None
        # if unit.is_idle:
        #     return GatherAction(target, self.state.bot.speedmining_positions[target_pos])
        elif len(unit.orders) >= 2:
            return None
        elif unit.is_gathering:
            return GatherAction(target, self.state.bot.speedmining_positions[target_pos])
        elif unit.is_returning:
            if not any(return_targets):
                return None
            return_target = min(return_targets, key=lambda th: th.distance_to(unit))
            return_point = self.state.bot.return_point[target_pos]
            return ReturnResource(return_target, return_point)
        # logger.warning(f"Unexpected worker behaviour {unit.orders=}")
        return Smart(target)
