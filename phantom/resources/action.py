import math
from dataclasses import dataclass
from functools import cached_property

import numpy as np
from loguru import logger
from sc2.unit import Unit
from sc2.units import Units

from phantom.common.action import Action, DoNothing, Smart
from phantom.common.distribute import _get_problem
from phantom.common.utils import pairwise_distances
from phantom.knowledge import Knowledge
from phantom.resources.gather import GatherAction, ReturnResource
from phantom.resources.observation import HarvesterAssignment, ResourceObservation


class SolverError(Exception):
    pass


@dataclass(frozen=True)
class ResourceAction:
    knowledge: Knowledge
    observation: ResourceObservation
    previous_assignment: HarvesterAssignment
    previous_hash: int

    @cached_property
    def harvester_assignment(self) -> HarvesterAssignment:
        if self.observation.gather_hash == self.previous_hash:
            return self.previous_assignment
        elif solution := self.solve():
            return solution
        else:
            logger.error("Harvester assignment solve failed")
            return self.previous_assignment

    def solve(self) -> HarvesterAssignment | None:
        harvesters = self.observation.harvesters
        resources = list(self.observation.mineral_fields + self.observation.gas_buildings)

        if not any(resources):
            return {}

        mineral_max = 2 * self.observation.mineral_fields.amount
        gas_max = sum(self.observation.harvester_target_of_gas(g) for g in self.observation.gas_buildings)

        if self.observation.observation.researched_speed:
            gas_target = self.gas_target
        elif self.observation.observation.bank.vespene < 100:
            # gas_target = min(gas_max, int(self.observation.observation.supply_workers) - mineral_max)
            gas_target = gas_max
        else:
            gas_target = 0
        gas_target = max(0, min(gas_max, gas_target - self.observation.observation.workers_in_geysers))

        harvester_max = mineral_max + gas_target
        if harvester_max < len(harvesters):
            harvesters = sorted(harvesters, key=lambda u: u.tag)[:harvester_max]

        if not any(harvesters):
            return {}

        harvester_to_resource = pairwise_distances(
            [h.position for h in harvesters],
            [self.knowledge.speedmining_positions[r.position.rounded] for r in resources],
        )

        return_distance = np.array([self.knowledge.return_distances[r.position.rounded] for r in resources])
        return_distance = np.repeat(return_distance[None, ...], len(harvesters), axis=0)

        assignment_cost = np.ones((len(harvesters), len(resources)))
        resource_index_by_position = {r.position.rounded: i for i, r in enumerate(resources)}
        for i, hi in enumerate(harvesters):
            if (ti := self.previous_assignment.get(hi.tag)) and (j := resource_index_by_position.get(ti)) is not None:
                assignment_cost[i, j] = 0.0

        n = len(harvesters)
        m = len(resources)

        cost = harvester_to_resource + return_distance + assignment_cost
        limit = np.full(m, 2.0)
        is_gas = np.array([1.0 if r.mineral_contents == 0 else 0.0 for r in resources])

        problem = _get_problem(n, m, True)
        problem.set_total(is_gas, gas_target)

        # problem = get_highspy_problem(n, m)
        # x = problem.solve(cost, limit, is_gas, gas_target)

        x = problem.solve(cost, limit)
        indices = x.argmax(axis=1)
        assignment = {
            ai.tag: resources[j].position.rounded
            for (i, ai), j in zip(enumerate(harvesters), indices, strict=False)
            if x[i, j] > 0
        }

        return assignment

    @cached_property
    def gas_target(self) -> int:
        return math.ceil(self.observation.harvesters.amount * self.observation.gas_ratio)

    def gather_with(self, unit: Unit, return_targets: Units) -> Action | None:
        if not (target_pos := self.harvester_assignment.get(unit.tag)):
            # logger.error(f"Unassinged harvester {unit}")
            return None
        if not (target := self.observation.resource_at.get(target_pos)):
            logger.error(f"No resource found at {target_pos}")
            return None
        if target.is_vespene_geyser and not (target := self.observation.gas_building_at.get(target_pos)):
            logger.error(f"No gas building found at {target_pos}")
            return None
        if unit.is_idle:
            return Smart(unit, target)
        elif len(unit.orders) >= 2:
            return DoNothing()
        elif unit.is_gathering:
            return GatherAction(unit, target, self.knowledge.speedmining_positions[target_pos])
        elif unit.is_returning:
            if not any(return_targets):
                return None
            return_target = min(return_targets, key=lambda th: th.distance_to(unit))
            return ReturnResource(unit, return_target)
        return Smart(unit, target)
