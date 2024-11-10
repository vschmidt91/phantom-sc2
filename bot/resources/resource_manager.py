import itertools
import math
from dataclasses import dataclass
from functools import cached_property
from itertools import chain
from typing import Iterator

import numpy as np
from loguru import logger
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.action import Action, DoNothing, Smart
from bot.base import BotBase
from bot.resources.gather import GatherAction, ReturnResource

STATIC_DEFENSE_TRIGGERS = {
    UnitTypeId.ROACHBURROWED: 0.5,
    UnitTypeId.MUTALISK: 0.3,
    UnitTypeId.PHOENIX: 0.3,
    UnitTypeId.ORACLE: 1.0,
    UnitTypeId.BANSHEE: 1.0,
}


def remaining(unit: Unit) -> int:
    if unit.is_mineral_field:
        if not unit.is_visible:
            return 1500
        else:
            return unit.mineral_contents
    elif unit.is_vespene_geyser:
        if not unit.is_visible:
            return 2250
        else:
            return unit.vespene_contents
    raise TypeError()


@dataclass(frozen=True)
class HarvesterAssignment:
    items: dict[int, Point2]

    @property
    def count(self) -> int:
        return len(self.items)

    @cached_property
    def target(self) -> set[Point2]:
        return set(self.items.values())

    def assigned_to(self, p: Point2) -> set[int]:
        return {u for u, t in self.items.items() if t == p}

    def assigned_to_set(self, ps: set[Point2]) -> set[int]:
        return {u for u, t in self.items.items() if t in ps}

    def assign(self, other: dict[int, Point2]) -> "HarvesterAssignment":
        return HarvesterAssignment({**self.items, **other})

    def unassign(self, other: set[int]) -> "HarvesterAssignment":
        return HarvesterAssignment({k: v for k, v in self.items.items() if k not in other})

    def __iter__(self) -> Iterator[int]:
        return iter(self.items)

    def __contains__(self, other: int) -> bool:
        return other in self.items


@dataclass(frozen=True)
class ResourceContext:
    bot: BotBase
    old_assignment: HarvesterAssignment
    harvesters: Units
    gas_buildings: Units
    vespene_geysers: Units
    mineral_fields: Units
    gas_ratio: float

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
    def harvester_tags(self) -> set[int]:
        return {h.tag for h in self.harvesters}

    @cached_property
    def gas_positions(self) -> set[Point2]:
        return set(self.gas_building_at)

    @cached_property
    def mineral_positions(self) -> set[Point2]:
        return set(self.mineral_field_at)

    @cached_property
    def workers_in_geysers(self) -> int:
        return int(self.bot.supply_workers) - self.bot.workers.amount

    # @lru_cache(maxsize=None)
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

    def pick_resource(self, assignment: HarvesterAssignment, targets: set[Point2]) -> Point2 | None:
        return max(
            targets,
            key=lambda u: self.harvester_target_at(u.position) - len(assignment.assigned_to(u.position)),
            default=None,
        )

    def pick_harvester(
        self, assignment: HarvesterAssignment, from_resources: set[Point2], close_to: Point2
    ) -> Unit | None:
        candidate_tags = assignment.assigned_to_set(from_resources)
        candidates = self.harvesters.filter(lambda h: h.tag in candidate_tags)
        if not candidates:
            return None
        return candidates.closest_to(close_to)

    def update_assignment(self, assignment: HarvesterAssignment) -> HarvesterAssignment:
        if assignment.count == 0:
            return split_initial_workers(self.mineral_fields, self.harvesters)
        else:
            return self.update_changes(assignment)

    def update_changes(self, assignment: HarvesterAssignment) -> HarvesterAssignment:

        # remove unassigned harvesters
        for tag in assignment:
            if tag in self.harvester_tags:
                continue
            target_pos = assignment.items[tag]
            target = self.resource_at[target_pos]
            if 0 < self.workers_in_geysers and target.is_vespene_geyser:
                # logger.info(f"in gas: {tag=}")
                continue
            assignment = assignment.unassign({tag})
            logger.info(f"MIA: {tag=}")

        # remove from unassigned resources
        for tag, target_pos in assignment.items.items():
            if target_pos in self.mineral_positions:
                if target_pos not in self.mineral_positions:
                    assignment = assignment.unassign({tag})
                    logger.info(f"Unassigning {tag} from mined out {target_pos=}")
            else:
                if target_pos not in self.gas_building_at:
                    assignment = assignment.unassign({tag})
                    logger.info(f"Unassigning {tag} from mined out {target_pos=}")

        # assign new harvesters
        def assignment_priority(a: HarvesterAssignment, h: Unit, t: Unit) -> float:
            return self.harvester_target_at(t.position) - len(a.assigned_to(t.position)) + np.exp(-h.distance_to(t))

        for harvester in self.harvesters:
            if harvester.tag in assignment:
                continue
            target = max(
                chain(self.mineral_fields.mineral_field, self.gas_buildings),
                key=lambda r: assignment_priority(assignment, harvester, r),
            )
            assignment = assignment.assign({harvester.tag: target.position})
            logger.info(f"Assigning {harvester=} to {target=}")

        return assignment

    def update_balance(self, assignment: HarvesterAssignment, gas_target: int) -> HarvesterAssignment:

        # transfer to/from gas
        gas_harvester_count = len(assignment.assigned_to_set(self.gas_positions))

        gas_max = sum(self.harvester_target_at(p) for p in self.gas_building_at)
        effective_gas_target = min(gas_max, gas_target)

        if gas_harvester_count < effective_gas_target:
            assignment = self.transfer_harvester(assignment, self.mineral_positions, self.gas_positions)
        elif effective_gas_target < gas_harvester_count:
            assignment = self.transfer_harvester(assignment, self.gas_positions, self.mineral_positions)
        else:
            assignment = self.balance_positions(assignment, self.mineral_positions)
            assignment = self.balance_positions(assignment, self.gas_positions)

        return assignment

    def transfer_harvester(
        self, assignment: HarvesterAssignment, from_resources: set[Point2], to_resources: set[Point2]
    ) -> HarvesterAssignment:
        if not (patch := self.pick_resource(assignment, to_resources)):
            return assignment
        if not (harvester := self.pick_harvester(assignment, from_resources, patch)):
            return assignment
        logger.info(f"Transferring {harvester=} to {patch=}")
        return assignment.assign({harvester.tag: patch})

    def balance_positions(self, assignment: HarvesterAssignment, ps: set[Point2]) -> HarvesterAssignment:
        oversaturated = [p for p in ps if self.harvester_target_at(p) < len(assignment.assigned_to(p))]
        if not any(oversaturated):
            return assignment
        undersaturated = [p for p in ps if len(assignment.assigned_to(p)) < self.harvester_target_at(p)]
        if not any(undersaturated):
            return assignment

        transfer_from, transfer_to = min(
            itertools.product(oversaturated, undersaturated), key=lambda p: p[0].distance_to(p[1])
        )

        # transfer_from = oversaturated[0]
        # transfer_to = undersaturated[0]

        harvester = next(iter(assignment.assigned_to(transfer_from)))
        assignment = assignment.assign({harvester: transfer_to})
        logger.info(f"Transferring {harvester=} to {transfer_to=}")
        return assignment


@dataclass(frozen=True)
class ResourceReport:
    context: ResourceContext
    assignment: HarvesterAssignment
    gas_target: int

    @property
    def max_harvesters(self) -> int:
        return sum(
            (
                2 * self.context.mineral_fields.amount,
                3 * self.context.vespene_geysers.amount,
            )
        )

    def gather_with(self, unit: Unit, return_targets: Units) -> Action | None:
        if not (target_pos := self.assignment.items.get(unit.tag)):
            logger.error(f"Unassinged harvester {unit}")
            return None
        if not (target := self.context.resource_at.get(target_pos)):
            logger.error(f"No resource found at {target_pos}")
            return None
        if target.is_vespene_geyser:
            if not (target := self.context.gas_building_at.get(target_pos)):
                logger.error(f"No gas building found at {target_pos}")
                return None
        if unit.is_idle:
            return Smart(unit, target)
        elif 2 <= len(unit.orders):
            return DoNothing()
        elif unit.is_gathering:
            return GatherAction(unit, target, self.context.bot.speedmining_positions.get(target_pos))
        elif unit.is_returning:
            assert any(return_targets)
            return_target = min(return_targets, key=lambda th: th.distance_to(unit))
            return ReturnResource(unit, return_target)
        return Smart(unit, target)


def split_initial_workers(patches: Units, harvesters: Units) -> HarvesterAssignment:
    harvester_set = set(harvesters)
    assignment = HarvesterAssignment({})
    while True:
        for patch in patches:
            if not harvester_set:
                return assignment
            harvester = min(harvester_set, key=lambda h: h.distance_to(patch))
            harvester_set.remove(harvester)
            assignment = assignment.assign({harvester.tag: patch.position})


def update_resources(context: ResourceContext) -> ResourceReport:

    if not context.mineral_fields:
        return ResourceReport(context, HarvesterAssignment({}), 0)

    assignment = context.old_assignment
    assignment = context.update_assignment(assignment)
    gas_target = math.ceil(assignment.count * context.gas_ratio)
    assignment = context.update_balance(assignment, gas_target)

    return ResourceReport(context, assignment, gas_target)
