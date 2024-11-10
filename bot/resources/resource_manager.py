import math
from dataclasses import dataclass
from functools import cached_property, lru_cache
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


def build_gasses(context: BotBase, gas_target: float) -> MacroPlan | None:
    gas_type = GAS_BY_RACE[context.race]
    gas_depleted = context.gas_buildings.filter(lambda g: not g.has_vespene).amount
    gas_pending = context.count(gas_type, include_actual=False)
    gas_have = context.count(gas_type, include_pending=False, include_planned=False)
    gas_max = sum(1 for _ in context.owned_geysers)
    gas_want = min(gas_max, gas_depleted + math.ceil((gas_target - 1) / 3))
    if gas_have + gas_pending < gas_want:
        return MacroPlan(gas_type)
    return None


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
    assignment: dict[int, Point2]

    @property
    def count(self) -> int:
        return len(self.assignment)

    @cached_property
    def target(self) -> set[Point2]:
        return set(self.assignment.values())

    def assigned_to(self, p: Point2) -> set[int]:
        return {u for u, t in self.assignment.items() if t == p}

    def assigned_to_set(self, ps: set[Point2]) -> set[int]:
        return {u for u, t in self.assignment.items() if t in ps}

    def __add__(self, other: dict[int, Point2]) -> "HarvesterAssignment":
        return HarvesterAssignment({**self.assignment, **other})

    def __sub__(self, other: set[int]) -> "HarvesterAssignment":
        return HarvesterAssignment({k: v for k, v in self.assignment.items() if k not in other})

    def __iter__(self) -> Iterator[int]:
        return iter(self.assignment)

    def __contains__(self, other: int) -> bool:
        return other in self.assignment


@dataclass(frozen=True)
class ResourceContext:
    bot: BotBase
    harvesters: Units
    gas_buildings: Units
    resources: Units
    gas_ratio: float

    @cached_property
    def resource_at(self) -> dict[Point2, Unit]:
        return {r.position: r for r in self.resources}

    @cached_property
    def gas_building_at(self) -> dict[Point2, Unit]:
        return {g.position: g for g in self.gas_buildings}

    @cached_property
    def resource_positions(self) -> set[Point2]:
        return {r.position for r in self.resources}

    @cached_property
    def harvester_tags(self) -> set[int]:
        return {h.tag for h in self.harvesters}

    @cached_property
    def geyser_positions(self) -> set[Point2]:
        return {g.position for g in self.resources.vespene_geyser}

    @cached_property
    def mineral_positions(self) -> set[Point2]:
        return {g.position for g in self.resources.mineral_field}

    @cached_property
    def workers_in_geysers(self) -> int:
        return int(self.bot.supply_workers) - self.bot.workers.amount

    @lru_cache(maxsize=None)
    def harvester_target_at(self, p: Point2) -> int:
        return self.harvester_target(self.resource_at[p])

    @lru_cache(maxsize=None)
    def harvester_target(self, unit: Unit) -> int:
        if unit.is_vespene_geyser:
            if not (building := self.gas_building_at.get(unit.position)):
                return 0
            elif not building.is_ready:
                return 0
            elif not remaining(unit):
                return 0
            return 3
        elif unit.is_mineral_field:
            if not remaining(unit):
                return 0
            return 2
        raise TypeError()

    def pick_gas(self, assignment: HarvesterAssignment) -> Unit | None:
        return max(
            self.gas_buildings,
            key=lambda g: self.harvester_target_at(g.position) - len(assignment.assigned_to(g.position)),
            default=None,
        )

    def pick_mineral(self, assignment: HarvesterAssignment) -> Unit | None:
        return max(
            self.resources.mineral_field,
            key=lambda r: self.harvester_target_at(r.position) - len(assignment.assigned_to(r.position)),
            default=None,
        )

    def pick_harvester(self, assignment: HarvesterAssignment, from_gas: bool, close_to: Point2) -> Unit | None:
        gas_harvesters = assignment.assigned_to_set(self.geyser_positions)
        candidates = self.harvesters.filter(lambda h: (h.tag in gas_harvesters) == from_gas)
        if not candidates:
            return None
        return candidates.closest_to(close_to)


@dataclass(frozen=True)
class ResourceReport:
    context: ResourceContext
    harvesters: HarvesterAssignment
    plans: list[MacroPlan]

    def gather_with(self, unit: Unit, return_targets: Units) -> Action | None:
        target_pos = self.harvesters.assignment[unit.tag]
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

    harvesters = HarvesterAssignment({})

    def update(self, context: ResourceContext) -> ResourceReport:

        if not context.resources:
            return ResourceReport(context, HarvesterAssignment({}), [])

        if self.harvesters.count == 0:
            self.harvesters = split_initial_workers(context.resources.mineral_field, context.harvesters)
            return ResourceReport(context, self.harvesters, [])

        old_assignment = self.harvesters
        new_assignment = old_assignment

        # remove unassigned harvesters
        for tag in new_assignment:
            if tag in context.harvester_tags:
                continue
            target_pos = new_assignment.assignment[tag]
            target = context.resource_at[target_pos]
            if 0 < context.workers_in_geysers and target.is_vespene_geyser:
                # logger.info(f"in gas: {tag=}")
                continue
            new_assignment -= {tag}
            logger.info(f"MIA: {tag=}")

        # assign new harvesters
        def assignment_priority(a: HarvesterAssignment, h: Unit, t: Unit) -> float:
            return context.harvester_target(t) - len(a.assigned_to(t.position)) + np.exp(-h.distance_to(t))

        for harvester in context.harvesters:
            if harvester.tag in new_assignment:
                continue
            target = max(
                chain(context.resources.mineral_field, context.gas_buildings),
                key=lambda r: assignment_priority(new_assignment, harvester, r)
            )
            new_assignment += {harvester.tag: target.position}
            logger.info(f"Assigning {harvester=} to {target=}")

        # unassign from mined out resources
        for tag, target in new_assignment.assignment.items():
            if target not in context.resource_positions:
                new_assignment -= {tag}
                logger.info(f"Unassigning {tag} from mined out {target=}")

        gas_target = self.harvesters.count * context.gas_ratio
        if 0 < gas_target:
            gas_target = max(3.0, gas_target)

        # transfer to/from gas
        gas_harvester_count = len(self.harvesters.assigned_to_set(context.geyser_positions))
        mineral_harvester_count = len(self.harvesters.assigned_to_set(context.mineral_positions))

        gas_max = sum(context.harvester_target(g) for g in context.resources.vespene_geyser)
        effective_gas_target = min(float(gas_max), gas_target)
        effective_gas_balance = gas_harvester_count - effective_gas_target

        mineral_target = sum(context.harvester_target(m) for m in context.resources.mineral_field)
        mineral_balance = mineral_harvester_count - mineral_target

        if effective_gas_balance < 0 or 0 < mineral_balance:
            if not (geyser := context.pick_gas(new_assignment)):
                pass
            elif not (harvester := context.pick_harvester(new_assignment, False, geyser.position)):
                pass
            else:
                new_assignment -= {harvester.tag}
                new_assignment += {harvester.tag: geyser.position}
                logger.info(f"Transferring {harvester=} to {geyser=}")
        elif 1 <= effective_gas_balance and mineral_balance < 0:
            if not (patch := context.pick_mineral(new_assignment)):
                pass
            elif not (harvester := context.pick_harvester(new_assignment, True, patch.position)):
                pass
            else:
                new_assignment -= {harvester.tag}
                new_assignment += {harvester.tag: patch.position}
                logger.info(f"Transferring {harvester=} to {patch=}")

        if transfer := next(
            (
                tag
                for tag, target in new_assignment.assignment.items()
                if (
                    target in context.mineral_positions
                    and context.harvester_target_at(target) < len(new_assignment.assigned_to(target))
                )
            ),
            None,
        ):
            if patch := next(
                (
                    m
                    for m in context.resources.mineral_field
                    if len(new_assignment.assigned_to(m.position)) < context.harvester_target(m)
                ),
                None,
            ):
                new_assignment -= {transfer}
                new_assignment += {transfer: patch.position}
                logger.info(f"Transferring {transfer=} to {patch=}")

        plans = list[MacroPlan]()
        if plan := build_gasses(context.bot, gas_target):
            plans.append(plan)

        self.harvesters = new_assignment

        return ResourceReport(context, new_assignment, plans)
