import math
from dataclasses import dataclass
from functools import cached_property, lru_cache
from itertools import chain
from typing import Iterator, Iterable

import numpy as np
from loguru import logger
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.action import Action, DoNothing, Smart
from bot.base import BotBase
from bot.constants import GAS_BY_RACE
from bot.macro import MacroPlan
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

    def __add__(self, other: dict[int, Point2]) -> "HarvesterAssignment":
        return HarvesterAssignment({**self.items, **other})

    def __sub__(self, other: set[int]) -> "HarvesterAssignment":
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

    #@lru_cache(maxsize=None)
    def harvester_target_at(self, p: Point2) -> int:
        if geyser := self.vespene_geyser_at.get(p):
            if not remaining(geyser):
                return 0
            return 3
        elif patch := self.mineral_field_at.get(p):
            if not remaining(patch):
                return 0
            return 2
        raise KeyError()

    def pick_gas(self, assignment: HarvesterAssignment) -> Unit | None:
        return max(
            (g for g in self.gas_buildings if len(assignment.assigned_to(g.position)) < self.harvester_target_at(g.position)),
            key=lambda g: self.harvester_target_at(g.position) - len(assignment.assigned_to(g.position)),
            default=None,
        )

    def pick_mineral(self, assignment: HarvesterAssignment) -> Unit | None:
        return max(
            self.mineral_fields,
            key=lambda r: self.harvester_target_at(r.position) - len(assignment.assigned_to(r.position)),
            default=None,
        )

    def pick_harvester(self, assignment: HarvesterAssignment, from_gas: bool, close_to: Point2) -> Unit | None:
        gas_harvesters = assignment.assigned_to_set(self.gas_positions)
        candidates = self.harvesters.filter(lambda h: (h.tag in gas_harvesters) == from_gas)
        if not candidates:
            return None
        return candidates.closest_to(close_to)

    def build_gasses(self, gas_target: float) -> Iterable[MacroPlan]:
        gas_type = GAS_BY_RACE[self.bot.race]
        gas_depleted = self.bot.gas_buildings.filter(lambda g: not g.has_vespene).amount
        gas_pending = self.bot.count(gas_type, include_actual=False)
        gas_have = self.gas_buildings.amount
        gas_max = self.vespene_geysers.amount
        gas_want = min(gas_max, gas_depleted + math.ceil((gas_target - 1) / 3))
        if gas_have + gas_pending < gas_want:
            yield MacroPlan(gas_type)


@dataclass(frozen=True)
class ResourceReport:
    context: ResourceContext
    assignment: HarvesterAssignment
    plans: list[MacroPlan]

    def gather_with(self, unit: Unit, return_targets: Units) -> Action | None:
        target_pos = self.assignment.items[unit.tag]
        target = self.context.resource_at[target_pos]
        if target.is_vespene_geyser:
            target = self.context.gas_building_at[target_pos]
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
            assignment += {harvester.tag: patch.position}


class ResourceManager:

    def update_changes(self, context: ResourceContext, assignment: HarvesterAssignment) -> HarvesterAssignment:

        # remove unassigned harvesters
        for tag in assignment:
            if tag in context.harvester_tags:
                continue
            target_pos = assignment.items[tag]
            target = context.resource_at[target_pos]
            if 0 < context.workers_in_geysers and target.is_vespene_geyser:
                # logger.info(f"in gas: {tag=}")
                continue
            assignment -= {tag}
            logger.info(f"MIA: {tag=}")

        # assign new harvesters
        def assignment_priority(a: HarvesterAssignment, h: Unit, t: Unit) -> float:
            return context.harvester_target_at(t.position) - len(a.assigned_to(t.position)) + np.exp(-h.distance_to(t))

        for harvester in context.harvesters:
            if harvester.tag in assignment:
                continue
            target = max(
                chain(context.mineral_fields.mineral_field, context.gas_buildings),
                key=lambda r: assignment_priority(assignment, harvester, r)
            )
            assignment += {harvester.tag: target.position}
            logger.info(f"Assigning {harvester=} to {target=}")

        # remove from unassigned resources
        for tag, target_pos in assignment.items.items():
            if target_pos in context.mineral_positions:
                if target_pos not in context.mineral_positions:
                    assignment -= {tag}
                    logger.info(f"Unassigning {tag} from mined out {target_pos=}")
            else:
                if target_pos not in context.gas_building_at:
                    assignment -= {tag}
                    logger.info(f"Unassigning {tag} from mined out {target_pos=}")

        return assignment

    def update_balance(self, context: ResourceContext, assignment: HarvesterAssignment, gas_target: float) -> HarvesterAssignment:

        # transfer to/from gas
        gas_harvester_count = len(assignment.assigned_to_set(context.gas_positions))
        mineral_harvester_count = len(assignment.assigned_to_set(context.mineral_positions))

        gas_max = sum(context.harvester_target_at(p) for p in context.vespene_geyser_at)
        effective_gas_target = min(float(gas_max), gas_target)
        effective_gas_balance = gas_harvester_count - effective_gas_target

        mineral_target = sum(context.harvester_target_at(p) for p in context.mineral_positions)
        mineral_balance = mineral_harvester_count - mineral_target

        if effective_gas_balance < 0 or 0 < mineral_balance:
            if not (geyser := context.pick_gas(assignment)):
                pass
            elif not (harvester := context.pick_harvester(assignment, False, geyser.position)):
                pass
            else:
                assignment -= {harvester.tag}
                assignment += {harvester.tag: geyser.position}
                logger.info(f"Transferring {harvester=} to {geyser=}")
        elif 1 <= effective_gas_balance and mineral_balance < 0:
            if not (patch := context.pick_mineral(assignment)):
                pass
            elif not (harvester := context.pick_harvester(assignment, True, patch.position)):
                pass
            else:
                assignment -= {harvester.tag}
                assignment += {harvester.tag: patch.position}
                logger.info(f"Transferring {harvester=} to {patch=}")

        if transfer := next(
            (
                tag
                for tag, p in assignment.items.items()
                if (
                    p in context.mineral_positions
                    and context.harvester_target_at(p) < len(assignment.assigned_to(p))
                )
            ),
            None,
        ):
            if patch := next(
                (
                    p
                    for p in context.mineral_positions
                    if len(assignment.assigned_to(p)) < context.harvester_target_at(p)
                ),
                None,
            ):
                assignment -= {transfer}
                assignment += {transfer: patch.position}
                logger.info(f"Transferring {transfer=} to {patch=}")

        return assignment

    def update_assignment(self, context: ResourceContext, assignment: HarvesterAssignment) -> HarvesterAssignment:
        if assignment.count == 0:
            return split_initial_workers(context.mineral_fields, context.harvesters)
        else:
            return self.update_changes(context, assignment)

    def update(self, context: ResourceContext) -> ResourceReport:

        if not context.mineral_fields:
            return ResourceReport(context, HarvesterAssignment({}), [])

        assignment = context.old_assignment
        assignment = self.update_assignment(context, assignment)
        gas_target = assignment.count * context.gas_ratio
        assignment = self.update_balance(context, assignment, gas_target)

        plans = list(chain(
            context.build_gasses(gas_target)
        ))
        return ResourceReport(context, assignment, plans)
