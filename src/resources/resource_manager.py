from __future__ import annotations

import math
from itertools import chain
from typing import TYPE_CHECKING, Counter, Dict, Iterable, Type, Optional

import numpy as np
from sc2.data import race_townhalls, race_gas
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.buff_id import BuffId
from sc2.position import Point2

from ..cost import Cost
from ..resources.resource_unit import ResourceUnit
from .base import Base
from .mineral_patch import MineralPatch
from .resource_base import ResourceBase
from .resource_group import ResourceGroup
from .vespene_geyser import VespeneGeyser
from ..behaviors.gather import GatherBehavior
from ..constants import GAS_BY_RACE, STATIC_DEFENSE_BY_RACE
from ..modules.module import AIModule
from ..modules.macro import MacroPlan

if TYPE_CHECKING:
    from ..ai_base import AIBase

MINING_RADIUS = 1.325
# MINING_RADIUS = 1.4

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
    return position -\
        np.dot(position - origin, orthogonal_direction) /\
        np.dot(orthogonal_direction, orthogonal_direction) *\
        orthogonal_direction


def get_intersections(
    position1: Point2,
    radius1: float,
    position2: Point2,
    radius2: float
) -> Iterable[Point2]:
    p01 = position2 - position1
    distance = np.linalg.norm(p01)
    if 0 < distance and abs(radius1 - radius2) <= distance <= radius1 + radius2:
        disc = (radius1 ** 2 - radius2 ** 2 + distance ** 2) / (2 * distance)
        height = math.sqrt(radius1 ** 2 - disc ** 2)
        middle = position1 + (disc / distance) * p01
        orthogonal = (height / distance) * np.array([p01.y, -p01.x])
        yield middle + orthogonal
        yield middle - orthogonal


class ResourceManager(AIModule):

    def __init__(self, ai: AIBase, bases: Iterable[Base]) -> None:
        super().__init__(ai)
        self.do_split = True
        self.bases = ResourceGroup(list(bases))
        self.set_speedmining_positions()
        self.resource_by_position: Dict[Point2, ResourceUnit] = {
            resource.position: resource
            for resource in self.bases.flatten()
        }
        self.harvesters_by_resource: Counter[ResourceUnit] = Counter[ResourceUnit]()
        self.income = Cost(0, 0, 0, 0)
        self.build_static_defense: bool = False

    @property
    def bases_taken(self) -> Iterable[Base]:
        return (
            b
            for b in self.bases
            if b.townhall and b.townhall.unit.is_ready
        )

    @property
    def mineral_patches(self) -> Iterable[MineralPatch]:
        return (
            r
            for b in self.bases_taken
            for r in b.mineral_patches
        )

    @property
    def vespene_geysers(self) -> Iterable[VespeneGeyser]:
        return (
            r
            for b in self.bases_taken
            for r in b.vespene_geysers
        )

    def add_harvester(self, harvester: GatherBehavior) -> None:
        gather_target = min(
            (x for b in self.bases_taken for x in b.flatten()),
            key=lambda r: r.harvester_target - self.harvesters_by_resource[r],
            default=None
        )
        # gather_target = min(
        #     (
        #         x
        #         for b in self.bases_taken
        #         for x in b.flatten()
        #         if 0 < x.harvester_target
        #     ),
        #     key=lambda r: harvester.unit.position.distance_to(r.position),
        #     default=None
        # )
        if gather_target:
            harvester.set_gather_target(gather_target)

    def update_bases(self) -> None:

        static_defense_priority = sum(
            STATIC_DEFENSE_TRIGGERS.get(enemy.type_id, 0.0)
            for enemy in self.ai.unit_manager.enemies.values()
        )
        self.build_static_defense = 1 < static_defense_priority

        townhalls_by_position = {
            townhall.unit.position: townhall
            for townhall_type in race_townhalls[self.ai.race]
            for townhall in chain(self.ai.unit_manager.actual_by_type[townhall_type],
                                  self.ai.unit_manager.pending_by_type[townhall_type])
        }

        static_defense_type = STATIC_DEFENSE_BY_RACE[self.ai.race]
        static_defense = {
            unit.unit.position: unit
            for unit in chain(
                self.ai.unit_manager.actual_by_type[static_defense_type],
                self.ai.unit_manager.pending_by_type[static_defense_type],
            )
            if unit.unit.type_id == static_defense_type
        }
        static_defense_pending = {
            unit.unit.position: unit
            for unit in self.ai.unit_manager.pending_by_type[static_defense_type]
            if unit.unit.type_id != static_defense_type
        }
        static_defense_plans = {
            plan.target: plan
            for plan in self.ai.macro.planned_by_type(static_defense_type)
        }

        for base in self.bases:
            base.townhall = townhalls_by_position.get(base.position)
            base.static_defense = static_defense.get(base.static_defense_position)

        if (
            self.build_static_defense
            and not any(static_defense_pending)
            and not any(static_defense_plans)
        ):
            for base in self.bases:
                if (
                    base.townhall
                    and base.townhall.unit.is_ready
                    and not base.static_defense
                ):

                    plan = self.ai.macro.add_plan(static_defense_type)
                    plan.target = base.static_defense_position
                    break

    def update_patches_and_geysers(self) -> None:

        gas_buildings_by_position = {
            gas.unit.position: gas
            for gas in self.ai.unit_manager.actual_by_type[race_gas[self.ai.race]]
        }

        resource_by_position = {
            unit.position: unit
            for unit in self.ai.resources
        }

        for base in self.bases:
            for patch in base.mineral_patches:
                patch.unit = resource_by_position.get(patch.position)
            for geyser in base.vespene_geysers:
                geyser.unit = resource_by_position.get(geyser.position)
                geyser.structure = gas_buildings_by_position.get(geyser.position)

    def balance_harvesters(self) -> None:

        harvester = next((
            h
            for h in self.ai.unit_manager.units.values()
            if (
                isinstance(h, GatherBehavior)
                and h.gather_target
                and isinstance(h.gather_target, MineralPatch)
                and h.gather_target.harvester_target < self.harvesters_by_resource[h.gather_target]
            )
        ), None)
        if not harvester:
            return

        transfer_to = next((
            resource
            for resource in self.mineral_patches
            if self.harvesters_by_resource[resource] < resource.harvester_target
        ), None)
        if not transfer_to:
            return

        harvester.set_gather_target(transfer_to)

    async def on_step(self) -> None:

        self.harvesters_by_resource = Counter[ResourceBase]((
            unit.gather_target
             for unit in self.ai.unit_manager.units.values()
             if isinstance(unit, GatherBehavior) and unit.gather_target
        ))

        self.update_patches_and_geysers()
        self.update_bases()
        self.update_gas()
        self.update_income()

        if self.do_split:
            harvesters = (
                u
                for u in self.ai.unit_manager.units.values()
                if isinstance(u, GatherBehavior)
            )
            self.bases[0].split_initial_workers(harvesters)
            self.do_split = False


        self.balance_harvesters()

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
                    intersections = list(get_intersections(
                        patch.position,
                        MINING_RADIUS,
                        patch2.position,
                        MINING_RADIUS
                    ))
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
        minerals = max(0, self.ai.macro.future_spending.minerals - self.ai.minerals)
        vespene = max(0, self.ai.macro.future_spending.vespene - self.ai.vespene)
        if minerals + vespene == 0:
            minerals = sum(b.mineral_patches.remaining for b in self.bases if b.townhall)
            vespene = sum(b.vespene_geysers.remaining for b in self.bases if b.townhall)

        # gas_ratio = vespene / max(1, vespene + minerals)
        # worker_type = race_worker[self.race]
        # gas_target = gas_ratio * self.count(worker_type, include_pending=False)

        vespene *= 1.2

        gas_ratio = 1 - 1 / (1 + vespene / max(1, minerals))
        gas_target = self.ai.state.score.food_used_economy * gas_ratio

        # print(minerals, vespene)

        if 0 < gas_target:
            gas_target = max(3.0, gas_target)

        return gas_target

    def build_gasses(self, gas_target: float):
        gas_type = GAS_BY_RACE[self.ai.race]
        gas_depleted = self.ai.gas_buildings.filter(lambda g: not g.has_vespene).amount
        gas_pending = self.ai.count(gas_type, include_actual=False)
        gas_have = self.ai.count(gas_type, include_pending=False, include_planned=False)
        gas_max = sum(1 for g in self.ai.get_owned_geysers())
        gas_want = min(gas_max, gas_depleted + math.ceil((gas_target - 1) / 3))
        if gas_have + gas_pending < gas_want:
            self.ai.macro.add_plan(gas_type)
        # elif gas_want + 1 < gas_have + gas_pending:
        #     gas_plans = sorted(self.ai.macro.planned_by_type(gas_type), key=lambda p: p.priority)
        #     for _, plan in zip(range(gas_have + gas_pending - gas_want), gas_plans):
        #         if plan.priority < math.inf:
        #             self.ai.macro.try_remove_plan(plan)

    def transfer_to_and_from_gas(self, gas_target: float):

        gas_harvester_count = self.harvester_count(VespeneGeyser)
        mineral_harvester_count = self.harvester_count(MineralPatch)
        gas_max = sum(g.harvester_target for g in self.vespene_geysers)
        effective_gas_target = min(float(gas_max), gas_target)
        effective_gas_balance = gas_harvester_count - effective_gas_target
        mineral_balance = mineral_harvester_count - sum(
            b.mineral_patches.harvester_target
            for b in self.bases
        )

        if (
            0 < mineral_harvester_count
            and (effective_gas_balance < 0 or 0 < mineral_balance)
            and (geyser := self.pick_resource(self.vespene_geysers))
            and (harvester := self.pick_harvester(MineralPatch, geyser.position))
        ):
            harvester.set_gather_target(geyser)
        elif (
            0 < gas_harvester_count
            and (1 <= effective_gas_balance and mineral_balance < 0)
            and (patch := self.pick_resource(self.mineral_patches))
            and (harvester := self.pick_harvester(VespeneGeyser, patch.position))
        ):
            harvester.set_gather_target(patch)

    def harvester_count(self, of_type: Type[ResourceUnit]) -> int:
        return sum(
            1
            for b in self.ai.unit_manager.units.values()
            if isinstance(b, GatherBehavior) and isinstance(b.gather_target, of_type)
        )

    def pick_resource(self, resources: Iterable[ResourceBase]) -> Optional[ResourceUnit]:
        return max(
            resources,
            key=lambda r: r.harvester_target - self.harvesters_by_resource[r],
            default=None,
        )

    def pick_harvester(self, from_type: Type[ResourceUnit], close_to: Point2) -> Optional[GatherBehavior]:
        return min(
            (
                b
                for b in self.ai.unit_manager.units.values()
                if isinstance(b, GatherBehavior) and isinstance(b.gather_target, from_type)
            ),
            key=lambda h: h.unit.position.distance_to(close_to),
            default=None
        )

    def update_income(self) -> None:

        self.income.minerals = self.ai.state.score.collection_rate_minerals
        self.income.vespene = self.ai.state.score.collection_rate_vespene

        larva_per_second = 0.0
        for hatchery in self.ai.townhalls:
            if hatchery.is_ready:
                larva_per_second += 1 / 11
                if hatchery.has_buff(BuffId.QUEENSPAWNLARVATIMER):
                    larva_per_second += 3 / 29
        self.income.larva = 60.0 * larva_per_second
