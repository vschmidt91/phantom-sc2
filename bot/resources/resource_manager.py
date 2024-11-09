import math
from itertools import chain
from typing import Counter, Iterable, Type, TypeVar

import numpy as np
from loguru import logger
from sc2.data import race_gas, race_townhalls
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from ..action import Action, DoNothing, Move, Smart
from ..base import BotBase
from ..constants import GAS_BY_RACE
from ..cost import Cost
from ..macro import MacroPlan
from ..resources.unit import ResourceUnit
from .gather import GatherAction, ReturnResource
from .mineral_patch import MineralPatch
from .vespene_geyser import VespeneGeyser

STATIC_DEFENSE_TRIGGERS = {
    UnitTypeId.ROACHBURROWED: 0.5,
    UnitTypeId.MUTALISK: 0.3,
    UnitTypeId.PHOENIX: 0.3,
    UnitTypeId.ORACLE: 1.0,
    UnitTypeId.BANSHEE: 1.0,
}

T = TypeVar("T", bound=ResourceUnit)


def get_gas_target(context: BotBase, future_spending: Cost) -> float:
    minerals = max(0.0, future_spending.minerals - context.minerals)
    vespene = max(0.0, future_spending.vespene - context.vespene)
    # if minerals + vespene == 0:
    #     minerals = sum(b.mineral_patches.remaining for b in self.bases if b.townhall)
    #     vespene = sum(b.vespene_geysers.remaining for b in self.bases if b.townhall)

    # gas_ratio = vespene / max(1, vespene + minerals)
    # worker_type = race_worker[self.race]
    # gas_target = gas_ratio * self.count(worker_type, include_pending=False)

    vespene *= 5 / 4

    n = context.supply_workers
    gas_target = n * vespene / max(1.0, minerals + vespene)
    # gas_ratio = 1 - 1 / (1 + vespene / max(1, minerals))
    # gas_target = self.state.score.food_used_economy * gas_ratio

    # print(minerals, vespene)

    if 0 < gas_target:
        gas_target = max(3.0, gas_target)

    return gas_target


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
    # elif gas_want + 1 < gas_have + gas_pending:
    #     gas_plans = sorted(self.macro.planned_by_type(gas_type), key=lambda p: p.priority)
    #     for _, plan in zip(range(gas_have + gas_pending - gas_want), gas_plans):
    #         if plan.priority < math.inf:
    #             self.macro.try_remove_plan(plan)


class ResourceManager:

    harvesters_by_resource = Counter[ResourceUnit]()
    harvester_assignment = dict[int, ResourceUnit]()

    def add_harvester(self, unit: Unit, targets: Iterable[ResourceUnit]) -> None:
        if gather_target := max(
            targets,
            key=lambda r: (
                r.harvester_target - self.harvesters_by_resource[r] + np.exp(-r.position.distance_to(unit.position))
            ),
            default=None,
        ):
            self.harvester_assignment[unit.tag] = gather_target
            self.harvesters_by_resource[gather_target] += 1

    def balance_harvesters(self, patches: Iterable[ResourceUnit]) -> None:
        if harvester_tag := next(
            (
                tag
                for tag, target in self.harvester_assignment.items()
                if (isinstance(target, MineralPatch) and target.harvester_target < self.harvesters_by_resource[target])
            ),
            None,
        ):
            if transfer_to := next(
                (resource for resource in patches if self.harvesters_by_resource[resource] < resource.harvester_target),
                None,
            ):
                self.harvester_assignment[harvester_tag] = transfer_to

    def assign_harvesters(
        self, context: BotBase, harvesters: Iterable[Unit], future_spending: Cost
    ) -> MacroPlan | None:

        # remove non-existent harvesters
        for tag, target in list(self.harvester_assignment.items()):
            if tag not in context.unit_tag_dict:
                might_be_in_geyser = context.supply_workers != context.workers.amount and isinstance(
                    target, VespeneGeyser
                )
                if not might_be_in_geyser:
                    del self.harvester_assignment[tag]
                    logger.info(f"Harvester MIA: {tag=}")

        # add new harvesters:
        for unit in harvesters:
            if unit.tag not in self.harvester_assignment:
                self.add_harvester(unit, context.all_taken_resources)

        self.harvesters_by_resource = Counter[ResourceUnit](self.harvester_assignment.values())

        gas_buildings_by_position = {gas.position: gas for gas in context.actual_by_type[race_gas[context.race]]}

        resource_by_position = {unit.position: unit for unit in context.resources}

        for base in context.bases:
            for patch in base.mineral_patches:
                patch.unit = resource_by_position.get(patch.position)
            for geyser in base.vespene_geysers:
                geyser.unit = resource_by_position.get(geyser.position)
                geyser.structure = gas_buildings_by_position.get(geyser.position)

        townhalls_by_position = {
            townhall.position: townhall
            for townhall_type in race_townhalls[context.race]
            for townhall in chain(context.actual_by_type[townhall_type], context.pending_by_type[townhall_type])
        }

        for base in context.bases:
            base.townhall = townhalls_by_position.get(base.position)

        gas_target = get_gas_target(context, future_spending)
        self.transfer_to_and_from_gas(context, gas_target)
        self.balance_harvesters(context.mineral_patches)
        return build_gasses(context, gas_target)

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

    def transfer_to_and_from_gas(self, context: BotBase, gas_target: float):
        gas_harvester_count = self.harvester_count(VespeneGeyser)
        mineral_harvester_count = self.harvester_count(MineralPatch)
        gas_max = sum(g.harvester_target for g in context.vespene_geysers)
        effective_gas_target = min(float(gas_max), gas_target)
        effective_gas_balance = gas_harvester_count - effective_gas_target

        mineral_target = sum(m.harvester_target for b in context.bases for m in b.mineral_patches)
        mineral_balance = mineral_harvester_count - mineral_target

        if effective_gas_balance < 0 or 0 < mineral_balance:
            if not (geyser := self.pick_resource(context.vespene_geysers)):
                pass
            elif not (harvester := self.pick_harvester(context, MineralPatch, geyser.position)):
                pass
            else:
                self.harvester_assignment[harvester.tag] = geyser
        elif 1 <= effective_gas_balance and mineral_balance < 0:
            if not (patch := self.pick_resource(context.mineral_patches)):
                pass
            elif not (harvester := self.pick_harvester(context, VespeneGeyser, patch.position)):
                pass
            else:
                self.harvester_assignment[harvester.tag] = patch

    def harvester_count(self, of_type: Type[ResourceUnit]) -> int:
        return sum(1 for h, t in self.harvester_assignment.items() if isinstance(t, of_type))

    def pick_resource(self, resources: Iterable[T]) -> T | None:

        resources = [r for r in resources if r.target_unit]
        if not any(resources):
            return None

        return max(resources, key=lambda r: r.harvester_target - self.harvesters_by_resource[r])

    def pick_harvester(self, context: BotBase, from_type: Type[ResourceUnit], close_to: Point2) -> Unit | None:
        harvesters = [
            u
            for h, t in self.harvester_assignment.items()
            if (u := context.unit_tag_dict.get(h)) and isinstance(t, from_type)
        ]
        if not any(harvesters):
            return None
        return min(harvesters, key=lambda u: u.distance_to(close_to))

    def split_initial_workers(self, patches: Iterable[ResourceUnit], harvesters: Iterable[Unit]):
        harvesters = set(harvesters)
        for _ in range(len(harvesters)):
            for patch in patches:
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
