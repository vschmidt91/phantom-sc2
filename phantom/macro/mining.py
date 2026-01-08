import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from ares.behaviors.macro.mining import TOWNHALL_TARGET
from cython_extensions import cy_closest_to
from loguru import logger
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from phantom.common.action import Action, Smart
from phantom.common.distribute import get_assignment_solver
from phantom.common.metrics import MetricAccumulator
from phantom.common.parameters import OptimizationTarget, ParameterManager, Prior
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

    async def execute(self, unit: Unit) -> bool:
        move_target = self.return_target.position.towards(unit, TOWNHALL_TARGET)
        if 0.75 < unit.position.distance_to(move_target) < 1.5:
            return unit.move(move_target) and unit.smart(self.return_target, queue=True)
        elif not unit.is_returning:
            return unit.return_resource()
        else:
            return True


class MiningParameters:
    def __init__(self, params: ParameterManager) -> None:
        self.return_distance_weight_log = params.optimize[OptimizationTarget.MiningEfficiency].add(Prior(1, 1))
        self.assignment_cost_log = params.optimize[OptimizationTarget.MiningEfficiency].add(Prior(0, 0.3))

    @property
    def return_distance_weight(self) -> float:
        return np.exp(self.return_distance_weight_log.value)

    @property
    def assignment_cost(self) -> float:
        return np.exp(self.assignment_cost_log.value)


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


class MiningState:
    def __init__(self, bot: "PhantomBot", params: ParameterManager) -> None:
        self.bot = bot
        self.params = MiningParameters(params)
        self.assignment: HarvesterAssignment = {}
        self.gather_hash = 0
        self.efficiency = MetricAccumulator()

    def step(self, observation: MiningContext) -> "MiningStep":
        action = MiningStep(self, observation)
        self.assignment = action.harvester_assignment
        self.gather_hash = observation.gather_hash

        income = observation.bot.income.minerals + observation.bot.income.vespene
        self.efficiency.add_value(income, len(observation.harvesters))

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

        if not any(resources):
            return {}

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
        optimal_assigned = math.ceil(n / m)
        max_assigned_mineral = max(optimal_assigned, self.context.bot.harvesters_per_mineral_field)
        max_assigned_gas = max(optimal_assigned, self.context.bot.harvesters_per_gas_building)
        gas_target = min(self.context.gas_target, max_assigned_gas * len(self.context.gas_buildings))

        cost = harvester_to_resource
        cost += self.state.params.return_distance_weight * return_distance
        cost += self.state.params.assignment_cost * assignment_cost
        is_gas = np.array([1.0 if r.mineral_contents == 0 else 0.0 for r in resources])
        limit = np.array([max_assigned_mineral if r.is_mineral_field else max_assigned_gas for r in resources])

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
        elif unit.is_returning or (unit.is_idle and unit.is_carrying_resource):
            if return_targets:
                return_target = cy_closest_to(unit.position, return_targets)
                return ReturnResource(return_target)
            else:
                return None
        return Smart(target)
