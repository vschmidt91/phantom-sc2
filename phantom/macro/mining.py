import math
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from ares.behaviors.macro.mining import TOWNHALL_TARGET
from cython_extensions import cy_closest_to
from loguru import logger
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from phantom.common.action import Action, Move, Smart
from phantom.common.cost import Cost
from phantom.common.distribute import get_assignment_solver
from phantom.common.metrics import MetricAccumulator
from phantom.common.point import Point, to_point
from phantom.common.unit_composition import UnitComposition
from phantom.common.utils import pairwise_distances
from phantom.learn.parameters import OptimizationTarget, ParameterManager, Prior
from phantom.observation import Observation

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
        self.return_distance_weight_log = params.optimize[OptimizationTarget.MiningEfficiency].add(
            "return_distance_weight_log", Prior(-3.0, 1.0)
        )
        self.assignment_cost_log = params.optimize[OptimizationTarget.MiningEfficiency].add(
            "assignment_cost_log", Prior(2.0, 1.0)
        )

    @property
    def return_distance_weight(self) -> float:
        return np.exp(self.return_distance_weight_log.value)

    @property
    def assignment_cost(self) -> float:
        return np.exp(self.assignment_cost_log.value)


class MiningSituation:
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


class MiningCommand:
    def __init__(self, bot: "PhantomBot", params: ParameterManager) -> None:
        self.bot = bot
        self.params = MiningParameters(params)
        self.assignment: HarvesterAssignment = {}
        self.gather_hash = 0
        self.efficiency = MetricAccumulator()
        self.gas_ratio = 0.0
        self.gas_target = 0
        self.harvesters = list[Unit]()
        self._composition_deficit: UnitComposition = {}
        self._planned_cost = Cost()
        self._harvester_exclude = set[int]()
        self._step: MiningStep | None = None

    def set_context(
        self,
        composition_deficit: UnitComposition,
        planned_cost: Cost,
        harvesters_exclude: Set[int],
    ) -> None:
        self._composition_deficit = dict(composition_deficit)
        self._planned_cost = planned_cost
        self._harvester_exclude = set(harvesters_exclude)

    @property
    def step_result(self) -> "MiningStep | None":
        return self._step

    def on_step(self, observation: Observation) -> None:
        required = Cost()
        required += self._planned_cost
        required += observation.bot.cost.of_composition(self._composition_deficit)
        required -= observation.bot.bank
        required = Cost.max(required, Cost())

        if required.minerals == 0 and required.vespene == 0:
            gas_ratio = 0.5
        else:
            gas_ratio = required.vespene / (required.minerals + required.vespene)
        self.gas_ratio = max(0, min(1, gas_ratio))

        harvesters = list[Unit]()
        harvesters.extend(observation.bot.workers.tags_not_in(self._harvester_exclude))
        harvesters.extend(observation.bot.workers_off_map.values())
        self.harvesters = harvesters

        gas_target = math.ceil(len(harvesters) * self.gas_ratio)
        if not observation.bot.researched_speed and observation.bot.harvestable_gas_buildings:
            gas_target = 2
        self.gas_target = gas_target

        def should_harvest_resource(r: Unit) -> bool:
            p = to_point(r.position)
            return observation.bot.mediator.is_position_safe(
                grid=observation.bot.ground_grid,
                position=observation.bot.gather_targets[p],
                weight_safety_limit=6.0,
            )

        mineral_fields = [m for m in observation.bot.all_taken_minerals if should_harvest_resource(m)]
        gas_buildings = [g for g in observation.bot.harvestable_gas_buildings if should_harvest_resource(g)]
        situation = MiningSituation(
            observation.bot,
            harvesters,
            mineral_fields,
            gas_buildings,
            gas_target,
        )
        self._step = self.step(situation)

    def get_actions(self, observation: Observation) -> Mapping[Unit, Action]:
        if self._step is None:
            return {}
        return {
            harvester: action
            for harvester in self.harvesters
            if (action := self._step.gather_with(harvester, observation.harvester_return_targets))
        }

    def step(self, situation: MiningSituation) -> "MiningStep":
        action = MiningStep(self, situation)
        self.assignment = action.harvester_assignment
        self.gather_hash = situation.gather_hash

        income = situation.bot.income.minerals + situation.bot.income.vespene
        self.efficiency.add_value(income, len(situation.harvesters))

        return action


class MiningStep:
    def __init__(
        self,
        state: MiningCommand,
        situation: MiningSituation,
    ):
        self.state = state
        self.situation = situation
        self.harvester_assignment = self._harvester_assignment()

    def _harvester_assignment(self) -> HarvesterAssignment:
        if self.situation.gather_hash == self.state.gather_hash:
            return self.state.assignment
        if (solution := self.solve()) is not None:
            return solution
        logger.error("Harvester assignment solve failed")
        return self.state.assignment

    def solve(self) -> HarvesterAssignment | None:
        harvesters = self.situation.harvesters
        resources = [*self.situation.mineral_fields, *self.situation.gas_buildings]

        if not resources:
            return {}
        if not harvesters:
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
        max_assigned_mineral = max(optimal_assigned, self.situation.bot.harvesters_per_mineral_field)
        max_assigned_gas = max(optimal_assigned, self.situation.bot.harvesters_per_gas_building)
        gas_target = min(self.situation.gas_target, max_assigned_gas * len(self.situation.gas_buildings))

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
        if not self._is_unit_safe(unit):
            return None
        if not (target_pos := self.harvester_assignment.get(unit.tag)):
            return None
        if not (target := self.situation.resource_by_position.get(target_pos)):
            logger.error(f"No resource found at {target_pos}")
            return None
        if len(unit.orders) >= 2:
            return None
        gather_target = self.state.bot.gather_targets[target_pos]
        if unit.is_gathering:
            if unit.order_target != target.tag:
                move_target = self.state.bot.mediator.find_path_next_point(
                    start=unit.position,
                    target=gather_target,
                    grid=self.state.bot.ground_grid,
                    sense_danger=False,
                )
                return Move(move_target)
            return GatherAction(target, gather_target)
        if unit.is_returning or (unit.is_idle and unit.is_carrying_resource):
            if return_targets:
                return_target = cy_closest_to(unit.position, return_targets)
                return ReturnResource(return_target)
            else:
                return None
        if unit.distance_to(gather_target) > 2.0:
            move_target = self.state.bot.mediator.find_path_next_point(
                start=unit.position,
                target=gather_target,
                grid=self.state.bot.ground_grid,
                sense_danger=False,
            )
            return Move(move_target)
        return Smart(target)

    def _is_unit_safe(self, unit: Unit, weight_safety_limit: float = 6.0) -> bool:
        return self.state.bot.mediator.is_position_safe(
            grid=self.state.bot.ground_grid,
            position=unit.position,
            weight_safety_limit=weight_safety_limit,
        )
