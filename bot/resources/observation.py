import itertools
from dataclasses import dataclass
from functools import cached_property
from typing import TypeAlias

import numpy as np
from loguru import logger
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.common.assignment import Assignment
from bot.common.main import BotBase
from bot.resources.utils import remaining

HarvesterAssignment: TypeAlias = Assignment[int, Point2]


def split_initial_workers(patches: Units, harvesters: Units, townhall: Unit) -> HarvesterAssignment:
    def cost(h: Unit, p: Unit) -> float:
        # simulate 3 mining trips
        initial_distance = h.distance_to(p) - h.radius - p.radius
        mining_distance = p.distance_to(townhall) - p.radius - townhall.radius
        return initial_distance + 6 * mining_distance

    a = Assignment.distribute(harvesters, patches, cost)
    return HarvesterAssignment({u.tag: p.position for u, p in a.items()})


@dataclass(frozen=True)
class ResourceObservation:
    bot: BotBase
    harvesters: Units
    gas_buildings: Units
    vespene_geysers: Units
    mineral_fields: Units
    gas_ratio: float

    @property
    def max_harvesters(self) -> int:
        return sum(
            (
                2 * self.mineral_fields.amount,
                3 * self.vespene_geysers.amount,
            )
        )

    @cached_property
    def resource_at(self) -> dict[Point2, Unit]:
        return self.mineral_field_at | self.gas_building_at

    @cached_property
    def mineral_field_at(self) -> dict[Point2, Unit]:
        return {r.position: r for r in self.mineral_fields}

    @cached_property
    def gas_building_at(self) -> dict[Point2, Unit]:
        return {g.position: g for g in self.gas_buildings}

    @cached_property
    def vespene_geyser_at(self) -> dict[Point2, Unit]:
        return {g.position: g for g in self.vespene_geysers}

    @cached_property
    def harvester_tags(self) -> frozenset[int]:
        return frozenset({h.tag for h in self.harvesters})

    @cached_property
    def gas_positions(self) -> frozenset[Point2]:
        return frozenset(self.gas_building_at)

    @cached_property
    def mineral_positions(self) -> frozenset[Point2]:
        return frozenset(self.mineral_field_at)

    @cached_property
    def workers_in_geysers(self) -> int:
        return int(self.bot.supply_workers) - self.bot.workers.amount

    # cache
    def harvester_target_at(self, p: Point2) -> int:
        if geyser := self.vespene_geyser_at.get(p):
            if not remaining(geyser):
                return 0
            return 3
        elif patch := self.mineral_field_at.get(p):
            if not remaining(patch):
                return 0
            return 2
        logger.error(f"Missing resource at {p}")
        return 0

    def pick_resource(self, assignment: HarvesterAssignment, targets: frozenset[Point2]) -> Point2 | None:

        def loss_fn(u: Point2) -> float:
            return self.harvester_target_at(u.position) - len(assignment.assigned_to(u.position))

        if not any(targets):
            return None
        return max(targets, key=loss_fn)

    def pick_harvester(
        self, assignment: HarvesterAssignment, from_resources: frozenset[Point2], close_to: Point2
    ) -> Unit | None:
        candidate_tags = assignment.assigned_to_set(from_resources)
        candidates = self.harvesters.filter(lambda h: h.tag in candidate_tags)
        if not candidates:
            return None
        return candidates.closest_to(close_to)

    def update_assignment(self, assignment: HarvesterAssignment) -> HarvesterAssignment:
        if not any(assignment):
            return split_initial_workers(self.mineral_fields, self.harvesters, self.bot.townhalls[0])
        else:
            return self.update_changes(assignment)

    def update_changes(self, assignment: HarvesterAssignment) -> HarvesterAssignment:

        # remove unassigned harvesters
        for tag, target_pos in assignment.items():
            if tag in self.harvester_tags:
                continue
            target_pos = assignment[tag]
            if target := self.resource_at.get(target_pos):
                if 0 < self.workers_in_geysers and target.is_vespene_geyser:
                    # logger.info(f"in gas: {tag=}")
                    continue
            assignment -= {tag}
            logger.info(f"MIA: {tag=}")

        # remove from unassigned resources
        for tag, target_pos in assignment.items():
            if target_pos not in self.resource_at:
                assignment -= {tag}
                logger.info(f"Unassigning {tag} from {target_pos=}")

        # assign new harvesters
        def assignment_priority(a: HarvesterAssignment, h: Unit, t: Unit) -> float:
            return self.harvester_target_at(t.position) - len(a.assigned_to(t.position)) + np.exp(-h.distance_to(t))

        for harvester in self.harvesters:
            if harvester.tag in assignment:
                continue
            target = max(
                itertools.chain(self.mineral_fields.mineral_field, self.gas_buildings),
                key=lambda r: assignment_priority(assignment, harvester, r),
            )
            assignment += {harvester.tag: target.position}
            logger.info(f"Assigning {harvester=} to {target=}")

        return assignment

    def update_balance(self, assignment: HarvesterAssignment, gas_target: int) -> HarvesterAssignment:

        # transfer to/from gas
        mineral_harvesters = len(assignment.assigned_to_set(self.mineral_positions))
        gas_harvesters = len(assignment.assigned_to_set(self.gas_positions))

        mineral_max = sum(self.harvester_target_at(p) for p in self.mineral_field_at)
        gas_max = sum(self.harvester_target_at(p) for p in self.gas_building_at)
        effective_gas_target = min(gas_max, gas_target)

        gas_balance = effective_gas_target - gas_harvesters
        mineral_target = min(mineral_max, len(assignment) - effective_gas_target)
        mineral_balance = mineral_target - mineral_harvesters

        if mineral_balance < gas_balance:
            assignment = self.transfer_harvester(assignment, self.mineral_positions, self.gas_positions)
        elif gas_balance + 1 < mineral_balance:
            assignment = self.transfer_harvester(assignment, self.gas_positions, self.mineral_positions)
        else:
            assignment = self.balance_positions(assignment, self.mineral_positions)
            assignment = self.balance_positions(assignment, self.gas_positions)

        return assignment

    def transfer_harvester(
        self, assignment: HarvesterAssignment, from_resources: frozenset[Point2], to_resources: frozenset[Point2]
    ) -> HarvesterAssignment:
        if not (patch := self.pick_resource(assignment, to_resources)):
            return assignment
        if not (harvester := self.pick_harvester(assignment, from_resources, patch)):
            return assignment
        logger.info(f"Transferring {harvester=} to {patch=}")
        return assignment + {harvester.tag: patch}

    def balance_positions(self, assignment: HarvesterAssignment, ps: frozenset[Point2]) -> HarvesterAssignment:
        oversaturated = [p for p in ps if self.harvester_target_at(p) < len(assignment.assigned_to(p))]
        if not any(oversaturated):
            return assignment
        undersaturated = [p for p in ps if len(assignment.assigned_to(p)) < self.harvester_target_at(p)]
        if not any(undersaturated):
            return assignment

        def loss_fn(p: Point2, q: Point2) -> float:
            return p.distance_to(q)

        transfer_from, transfer_to = min(
            itertools.product(oversaturated, undersaturated), key=lambda p: loss_fn(p[0], p[1])
        )
        harvester = next(iter(assignment.assigned_to(transfer_from)))
        assignment += {harvester: transfer_to}
        logger.info(f"Transferring {harvester=} to {transfer_to=}")
        return assignment
