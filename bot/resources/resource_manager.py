import math
from itertools import chain
from typing import Counter, Iterable, Type

import numpy as np
from sc2.constants import IS_DETECTOR
from sc2.data import race_gas, race_townhalls
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from ..action import Action, DoNothing, Move, Smart
from ..components.base import Component
from ..constants import GAS_BY_RACE, STATIC_DEFENSE_BY_RACE
from ..resources.resource_unit import ResourceUnit
from .base import Base
from .gather import GatherAction, ReturnResource
from .mineral_patch import MineralPatch
from .vespene_geyser import VespeneGeyser

MINING_RADIUS = 1.325

MINERAL_RADIUS = 1.125
HARVESTER_RADIUS = 0.375

STATIC_DEFENSE_TRIGGERS = {
    UnitTypeId.ROACHBURROWED: 0.5,
    UnitTypeId.MUTALISK: 0.3,
    UnitTypeId.PHOENIX: 0.3,
    UnitTypeId.ORACLE: 1.0,
    UnitTypeId.BANSHEE: 1.0,
}


def project_point_onto_line(origin: Point2, direction: Point2, position: Point2) -> Point2:
    orthogonal_direction = Point2((direction[1], -direction[0]))
    return (
        position
        - np.dot(position - origin, orthogonal_direction)
        / np.dot(orthogonal_direction, orthogonal_direction)
        * orthogonal_direction
    )


def get_intersections(position1: Point2, radius1: float, position2: Point2, radius2: float) -> Iterable[Point2]:
    p01 = position2 - position1
    distance = np.linalg.norm(p01)
    if 0 < distance and abs(radius1 - radius2) <= distance <= radius1 + radius2:
        disc = (radius1**2 - radius2**2 + distance**2) / (2 * distance)
        height = math.sqrt(radius1**2 - disc**2)
        middle = position1 + (disc / distance) * p01
        orthogonal = (height / distance) * np.array([p01.y, -p01.x])
        yield middle + orthogonal
        yield middle - orthogonal


class ResourceManager(Component):

    resource_by_position: dict[Point2, ResourceUnit] = {}
    harvesters_by_resource: Counter[ResourceUnit] = Counter[ResourceUnit]()
    build_static_defense: bool = False
    harvester_assignment: dict[int, ResourceUnit] = {}

    def initialize_resources(self) -> None:
        self.resource_by_position = {resource.position: resource for resource in self.all_resources}
        self.resource_by_position.update({resource.position: resource for resource in self.all_resources})
        self.set_speedmining_positions()

    @property
    def owned_geysers(self) -> Iterable[VespeneGeyser]:
        for base in self.bases:
            if not base.townhall:
                continue
            if not base.townhall.is_ready:
                continue
            if base.townhall.type_id not in race_townhalls[self.race]:
                continue
            for geyser in base.vespene_geysers:
                yield geyser

    @property
    def all_resources(self) -> Iterable[ResourceUnit]:
        return chain(self.mineral_patches, self.vespene_geysers)

    @property
    def all_taken_resources(self) -> Iterable[ResourceUnit]:
        return chain.from_iterable(chain(b.mineral_patches, b.vespene_geysers) for b in self.bases_taken)

    @property
    def bases_taken(self) -> Iterable[Base]:
        townhall_positions = {th.position for th in self.townhalls if th.is_ready}
        return (b for b in self.bases if b.position in townhall_positions)

    @property
    def mineral_patches(self) -> Iterable[MineralPatch]:
        return (r for b in self.bases_taken for r in b.mineral_patches)

    @property
    def vespene_geysers(self) -> Iterable[VespeneGeyser]:
        return (r for b in self.bases_taken for r in b.vespene_geysers)

    @property
    def max_harvesters(self) -> int:
        workers = sum(b.harvester_target for b in self.bases_taken)
        workers += 16 * self.townhalls.not_ready.amount
        workers += 3 * self.gas_buildings.not_ready.amount
        return workers

    def units_detecting(self, unit: Unit) -> Iterable[Unit]:
        for detector_type in IS_DETECTOR:
            for detector in self.actual_by_type[detector_type]:
                distance = detector.position.distance_to(unit.position)
                if distance <= detector.radius + detector.detect_range + unit.radius:
                    yield detector

    def add_harvester(self, unit: Unit) -> None:
        if gather_target := max(
            self.all_taken_resources,
            key=lambda r: (
                r.harvester_target - self.harvesters_by_resource[r] + np.exp(-r.position.distance_to(unit.position))
            ),
            default=None,
        ):
            self.harvester_assignment[unit.tag] = gather_target
            self.harvesters_by_resource[gather_target] += 1

    def update_bases(self) -> None:
        static_defense_priority = sum(STATIC_DEFENSE_TRIGGERS.get(enemy.type_id, 0.0) for enemy in self.all_enemy_units)
        self.build_static_defense = 1 <= static_defense_priority

        townhalls_by_position = {
            townhall.position: townhall
            for townhall_type in race_townhalls[self.race]
            for townhall in chain(self.actual_by_type[townhall_type], self.pending_by_type[townhall_type])
        }

        static_defense_type = STATIC_DEFENSE_BY_RACE[self.race]
        static_defense = {
            unit.position: unit
            for unit in chain(
                self.actual_by_type[static_defense_type],
                self.pending_by_type[static_defense_type],
            )
            if unit.type_id == static_defense_type
        }
        static_defense_pending = {
            unit.position: unit
            for unit in self.pending_by_type[static_defense_type]
            if unit.type_id != static_defense_type
        }
        static_defense_plans = {plan.target: plan for plan in self.planned_by_type(static_defense_type)}

        for base in self.bases:
            base.townhall = townhalls_by_position.get(base.position)
            base.static_defense = static_defense.get(base.static_defense_position)

        if self.build_static_defense and not any(static_defense_pending) and not any(static_defense_plans):
            for base in self.bases:
                if base.townhall and base.townhall.is_ready and not base.static_defense:
                    plan = self.add_plan(static_defense_type)
                    plan.target = base.static_defense_position
                    break

    def update_patches_and_geysers(self) -> None:
        gas_buildings_by_position = {gas.position: gas for gas in self.actual_by_type[race_gas[self.race]]}

        resource_by_position = {unit.position: unit for unit in self.resources}

        for base in self.bases:
            for patch in base.mineral_patches:
                patch.unit = resource_by_position.get(patch.position)
            for geyser in base.vespene_geysers:
                geyser.unit = resource_by_position.get(geyser.position)
                geyser.structure = gas_buildings_by_position.get(geyser.position)

    def balance_harvesters(self) -> None:
        if harvester_tag := next(
            (
                tag
                for tag, target in self.harvester_assignment.items()
                if (isinstance(target, MineralPatch) and target.harvester_target < self.harvesters_by_resource[target])
            ),
            None,
        ):
            if transfer_to := next(
                (
                    resource
                    for resource in self.mineral_patches
                    if self.harvesters_by_resource[resource] < resource.harvester_target
                ),
                None,
            ):
                self.harvester_assignment[harvester_tag] = transfer_to

    def assign_harvesters(self, harvesters: Iterable[Unit]) -> None:

        # remove non-existent harvesters
        for tag, target in list(self.harvester_assignment.items()):
            if tag not in self.unit_tag_dict:
                might_be_in_geyser = self.supply_workers != self.workers.amount and isinstance(target, VespeneGeyser)
                if not might_be_in_geyser:
                    del self.harvester_assignment[tag]

        # add new harvesters:
        for unit in harvesters:
            if unit.tag not in self.harvester_assignment:
                self.add_harvester(unit)

        self.harvesters_by_resource = Counter[ResourceUnit](self.harvester_assignment.values())

        self.update_patches_and_geysers()
        self.update_bases()
        self.update_gas()
        self.balance_harvesters()

    def gather_with(self, unit: Unit, return_targets: Units) -> Action | None:
        if not (target := self.harvester_assignment.get(unit.tag)):
            return None
        elif not target.remaining:
            return None
        elif not (target_unit := target.target_unit):
            return None
        elif not (
            return_target := min(
                return_targets,
                key=lambda th: th.distance_to(unit),
                default=None,
            )
        ):
            return None
        elif not target_unit.is_ready:
            return Move(unit, target_unit.position)
        elif unit.is_idle:
            return Smart(unit, target_unit)
        elif 2 <= len(unit.orders):
            return DoNothing()
        elif unit.is_gathering:
            return GatherAction(unit, target)
        elif unit.is_returning:
            return ReturnResource(unit, return_target)
        return Smart(unit, target_unit)

    def set_speedmining_positions(self) -> None:
        for base in self.bases:
            for patch in base.mineral_patches:
                target = patch.position.towards(base.position, MINING_RADIUS)
                for patch2 in base.mineral_patches:
                    if patch.position == patch2.position:
                        continue
                    position = project_point_onto_line(target, target - base.position, patch2.position)
                    distance1 = patch.position.distance_to(base.position)
                    distance2 = patch2.position.distance_to(base.position)
                    if distance1 < distance2:
                        continue
                    if MINING_RADIUS <= patch2.position.distance_to(position):
                        continue
                    intersections = list(
                        get_intersections(patch.position, MINING_RADIUS, patch2.position, MINING_RADIUS)
                    )
                    if intersections:
                        intersection1, intersection2 = intersections
                        if intersection1.distance_to(base.position) < intersection2.distance_to(base.position):
                            target = intersection1
                        else:
                            target = intersection2
                        break
                patch.speedmining_target = target

    def update_gas(self):
        gas_target = self.get_gas_target()
        self.transfer_to_and_from_gas(gas_target)
        self.build_gasses(gas_target)

    def get_gas_target(self) -> float:
        minerals = max(0, self.future_spending.minerals - self.minerals)
        vespene = max(0, self.future_spending.vespene - self.vespene)
        # if minerals + vespene == 0:
        #     minerals = sum(b.mineral_patches.remaining for b in self.bases if b.townhall)
        #     vespene = sum(b.vespene_geysers.remaining for b in self.bases if b.townhall)

        # gas_ratio = vespene / max(1, vespene + minerals)
        # worker_type = race_worker[self.race]
        # gas_target = gas_ratio * self.count(worker_type, include_pending=False)

        vespene *= 5 / 4

        n = self.supply_workers
        gas_target = n * vespene / max(1, minerals + vespene)
        # gas_ratio = 1 - 1 / (1 + vespene / max(1, minerals))
        # gas_target = self.state.score.food_used_economy * gas_ratio

        # print(minerals, vespene)

        if 0 < gas_target:
            gas_target = max(3.0, gas_target)

        return gas_target

    def build_gasses(self, gas_target: float):
        gas_type = GAS_BY_RACE[self.race]
        gas_depleted = self.gas_buildings.filter(lambda g: not g.has_vespene).amount
        gas_pending = self.count(gas_type, include_actual=False)
        gas_have = self.count(gas_type, include_pending=False, include_planned=False)
        gas_max = sum(1 for g in self.owned_geysers)
        gas_want = min(gas_max, gas_depleted + math.ceil((gas_target - 1) / 3))
        if gas_have + gas_pending < gas_want:
            self.add_plan(gas_type)
        # elif gas_want + 1 < gas_have + gas_pending:
        #     gas_plans = sorted(self.macro.planned_by_type(gas_type), key=lambda p: p.priority)
        #     for _, plan in zip(range(gas_have + gas_pending - gas_want), gas_plans):
        #         if plan.priority < math.inf:
        #             self.macro.try_remove_plan(plan)

    def transfer_to_and_from_gas(self, gas_target: float):
        gas_harvester_count = self.harvester_count(VespeneGeyser)
        mineral_harvester_count = self.harvester_count(MineralPatch)
        gas_max = sum(g.harvester_target for g in self.vespene_geysers)
        effective_gas_target = min(float(gas_max), gas_target)
        effective_gas_balance = gas_harvester_count - effective_gas_target
        mineral_balance = mineral_harvester_count - sum(b.mineral_patches.harvester_target for b in self.bases)

        if (
            0 < mineral_harvester_count
            and (effective_gas_balance < 0 or 0 < mineral_balance)
            and (geyser := self.pick_resource(self.vespene_geysers))
            and (harvester := self.pick_harvester(MineralPatch, geyser.position))
        ):
            self.harvester_assignment[harvester.tag] = geyser
        elif (
            0 < gas_harvester_count
            and (1 <= effective_gas_balance and mineral_balance < 0)
            and (patch := self.pick_resource(self.mineral_patches))
            and (harvester := self.pick_harvester(VespeneGeyser, patch.position))
        ):
            self.harvester_assignment[harvester.tag] = patch

    def harvester_count(self, of_type: Type[ResourceUnit]) -> int:
        return sum(1 for h, t in self.harvester_assignment.items() if isinstance(t, of_type))

    def pick_resource(self, resources: Iterable[ResourceUnit]) -> ResourceUnit | None:

        resources = [r for r in resources if r.target_unit]
        if not any(resources):
            return None

        return max(resources, key=lambda r: r.harvester_target - self.harvesters_by_resource[r])

    def pick_harvester(self, from_type: Type[ResourceUnit], close_to: Point2) -> Unit | None:
        harvesters = [
            u
            for h, t in self.harvester_assignment.items()
            if (u := self.unit_tag_dict.get(h)) and isinstance(t, from_type)
        ]
        if not any(harvesters):
            return None
        return min(harvesters, key=lambda u: u.distance_to(close_to))

    def split_initial_workers(self, harvesters: Iterable[Unit]):
        harvesters = set(harvesters)
        for _ in range(len(harvesters)):
            for patch in self.mineral_patches:
                if not patch.unit:
                    continue
                harvester = min(
                    harvesters,
                    key=lambda h: h.position.distance_to(patch.unit.position) if patch.unit else np.inf,
                    default=None,
                )
                if not harvester:
                    return
                harvesters.remove(harvester)
                self.harvester_assignment[harvester.tag] = patch
