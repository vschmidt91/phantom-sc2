from __future__ import annotations

import random
import math
from functools import cmp_to_key
from itertools import chain
from typing import List, TYPE_CHECKING, Union, Optional, Iterable, Dict

from sc2.data import race_townhalls
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.ability_id import AbilityId
from sc2.unit_command import UnitCommand
from sc2.unit import Unit
from sc2.position import Point2

from ..units.unit import AIUnit
from .module import AIModule
from ..constants import ITEM_TRAINED_FROM_WITH_EQUIVALENTS, MACRO_INFO, GAS_BY_RACE
from ..constants import REQUIREMENTS, WITH_TECH_EQUIVALENTS
from ..cost import Cost
from ..utils import PlacementNotFoundException, time_to_reach

if TYPE_CHECKING:
    from ..ai_base import AIBase

MacroId = Union[UnitTypeId, UpgradeId]


def compare_plans(plan_a: MacroPlan, plan_b: MacroPlan) -> int:
    if plan_a.priority < plan_b.priority:
        return -1
    elif plan_b.priority < plan_a.priority:
        return +1
    elif plan_a.plan_id < plan_b.plan_id:
        return +1
    elif plan_b.plan_id < plan_a.plan_id:
        return -1
    return 0


class MacroPlan:

    def __init__(self, plan_id: int, item: MacroId):
        self.plan_id = plan_id
        self.item = item
        self.target: Union[Unit, Point2, None] = None
        self.priority: float = 0.0
        self.max_distance: Optional[int] = 4
        self.eta: float = math.inf

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.item}, {self.target}, {self.priority}, {self.eta})"

    def __hash__(self) -> int:
        return hash(self.plan_id)


class MacroModule(AIModule):

    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)
        self.next_plan_id: int = 0
        self.future_spending = Cost(0, 0, 0, 0)
        self.future_timeframe = 0.0
        self.unassigned_plans: List[MacroPlan] = list()
        self.composition: Dict[UnitTypeId, int] = dict()

    def add_plan(self, item: MacroId) -> MacroPlan:
        self.next_plan_id += 1
        plan = MacroPlan(self.next_plan_id, item)
        self.unassigned_plans.append(plan)
        return plan

    def try_remove_plan(self, plan: MacroPlan) -> bool:
        if plan in self.unassigned_plans:
            self.unassigned_plans.remove(plan)
            return True
        for behavior in self.ai.unit_manager.units.values():
            if isinstance(behavior, MacroBehavior) and behavior.plan == plan:
                behavior.plan = None
                return True
        return False

    def enumerate_plans(self) -> Iterable[MacroPlan]:
        unit_plans = (
            behavior.plan
            for behavior in self.ai.unit_manager.units.values()
            if isinstance(behavior, MacroBehavior) and behavior.plan
        )
        return chain(unit_plans, self.unassigned_plans)

    def planned_by_type(self, item: MacroId) -> Iterable[MacroPlan]:
        return (
            plan
            for plan in self.enumerate_plans()
            if plan.item == item
        )

    def make_composition(self):
        if 200 <= self.ai.supply_used:
            return
        composition_have = {
            unit: self.ai.count(unit)
            for unit in self.composition
        }
        for unit, count in self.composition.items():
            if count < 1:
                continue
            elif count <= composition_have[unit]:
                continue
            if any(self.ai.get_missing_requirements(unit)):
                continue
            priority = -self.ai.count(unit, include_planned=False) / count
            for plan in self.planned_by_type(unit):
                if plan.priority == math.inf:
                    continue
                plan.priority = priority
                break
            else:
                plan = self.add_plan(unit)
                plan.priority = priority

    async def on_step(self) -> None:

        self.make_composition()
        self.make_tech()

        reserve = Cost(0, 0, 0, 0)

        trainers = {
            behavior
            for behavior in self.ai.unit_manager.units.values()
            if (
                    isinstance(behavior, MacroBehavior)
                    and not behavior.plan
            )
        }

        plans = sorted(
            self.enumerate_plans(),
            key=cmp_to_key(compare_plans),
            # key = lambda t : t.priority,
            reverse=True
        )

        trainer_by_plan = {
            behavior.plan: behavior
            for behavior in self.ai.unit_manager.units.values()
            if isinstance(behavior, MacroBehavior) and behavior.plan
        }

        for i, plan in enumerate(plans):

            cost = self.ai.get_cost(plan.item)

            if (
                any(self.ai.get_missing_requirements(plan.item))
                and plan.priority == math.inf
            ):
                break

            if (2 if self.ai.extractor_trick_enabled else 1) <= i and plan.priority == math.inf:
                break

            if not (trainer := trainer_by_plan.get(plan)):
                if trainer := self.search_trainer(trainers, plan.item):
                    self.unassigned_plans.remove(plan)
                    trainer.plan = plan
                    trainers.remove(trainer)
                else:
                    if plan.priority == math.inf:
                        reserve += cost
                    # if (tf := UNIT_TRAINED_FROM.get(plan.item)) and UnitTypeId.LARVA in tf:
                    continue

            if any(self.ai.get_missing_requirements(plan.item)):
                continue

            # if type(plan.item) == UnitTypeId:
            #     cost = self.ai.techtree.units[plan.item].cost
            # elif type(plan.item) == UpgradeId:
            #     cost = self.ai.techtree.upgrades[plan.item].cost2
            # else:
            #     raise TypeError()

            if not (trainer.unit and trainer.macro_ability and trainer.unit.is_using_ability(trainer.macro_ability)):
                reserve += cost

            if plan.target is None:
                try:
                    plan.target = await self.get_target(trainer, plan)
                except PlacementNotFoundException:
                    continue

            # if (
            #     plan.priority < math.inf
            #     and self.ai.is_structure(plan.item)
            #     and isinstance(plan.target, Point2)
            #     and not await self.ai.can_place_single(plan.item, plan.target)
            # ):
            #     self.remove_plan(plan)
            #     continue

            if any(self.ai.get_missing_requirements(plan.item)):
                plan.eta = math.inf
            else:
                eta = 0.0
                if 0 < cost.minerals:
                    eta = max(eta, 60 * (reserve.minerals - self.ai.minerals)
                        / max(1, self.ai.resource_manager.income.minerals))
                if 0 < cost.vespene:
                    eta = max(eta, 60 * (reserve.vespene - self.ai.vespene)
                        / max(1, self.ai.resource_manager.income.vespene))
                if 0 < cost.larva:
                    eta = max(eta, 60 * (reserve.larva - self.ai.larva.amount)
                        / max(1, self.ai.resource_manager.income.larva))
                if 0 < cost.food:
                    if self.ai.supply_left < cost.food:
                        eta = math.inf
                plan.eta = eta

        cost_zero = Cost(0, 0, 0, 0)
        future_spending = cost_zero
        future_spending += sum((
            self.ai.get_cost(plan.item)
            for plan in self.ai.macro.unassigned_plans
        ), cost_zero)
        future_spending += sum((
            self.ai.get_cost(b.plan.item)
            for b in self.ai.unit_manager.units.values()
            if isinstance(b, MacroBehavior) and b.plan
        ), cost_zero)
        future_spending += sum((
            self.ai.get_cost(unit) * max(0, count - self.ai.count(unit))
            for unit, count in self.composition.items()
        ), cost_zero)
        self.future_spending = future_spending

        future_timeframe = 3 / 60
        if 0 < future_spending.minerals:
            future_timeframe = max(
                future_timeframe,
                future_spending.minerals / max(1, self.ai.resource_manager.income.minerals)
            )
        if 0 < future_spending.vespene:
            future_timeframe = max(
                future_timeframe,
                future_spending.vespene / max(1, self.ai.resource_manager.income.vespene)
            )
        if 0 < future_spending.larva:
            future_timeframe = max(
                future_timeframe,
                future_spending.larva / max(1, self.ai.resource_manager.income.larva)
            )
        self.future_timeframe = future_timeframe

    async def get_target(self,
        trainer: MacroBehavior,
        objective: MacroPlan
    ) -> Union[Unit, Point2, None]:
        gas_type = GAS_BY_RACE[self.ai.race]
        if objective.item == gas_type:
            exclude_positions = {
                geyser.position
                for geyser in self.ai.gas_buildings
            }
            exclude_tags = {
                order.target
                for unit in self.ai.unit_manager.pending_by_type[gas_type]
                for order in unit.unit.orders
                if isinstance(order.target, int)
            }
            exclude_tags.update({
                step.target.tag
                for step in self.planned_by_type(gas_type)
                if isinstance(step.target, Unit)
            })
            geysers = [
                geyser
                for geyser in self.ai.get_owned_geysers()
                if (
                        geyser.position not in exclude_positions
                        and geyser.tag not in exclude_tags
                )
            ]
            if not any(geysers):
                raise PlacementNotFoundException()
            else:
                return random.choice(geysers)

        if not (entry := MACRO_INFO.get(trainer.unit.type_id)):
            return None
        if not (data := entry.get(objective.item)):
            return None
        # data = MACRO_INFO[trainer.unit.type_id][objective.item]

        if "requires_placement_position" in data:
            position = await self.get_target_position(objective.item)
            with_addon = objective in {UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT}

            if objective.max_distance is not None:
                max_distance = objective.max_distance
                position = await self.ai.find_placement(
                    trainer.macro_ability,
                    position,
                    max_distance=max_distance,
                    placement_step=1,
                    addon_place=with_addon
                )
            if position is None:
                raise PlacementNotFoundException()
            else:
                return position
        else:
            return None

    def search_trainer(self,
        trainers: Iterable[MacroBehavior],
        item: MacroId
    ) -> Optional[MacroBehavior]:

        trainer_types = ITEM_TRAINED_FROM_WITH_EQUIVALENTS[item]

        trainers_filtered = (
            trainer
            for trainer in trainers
            if (
                trainer.unit.type_id in trainer_types
                and trainer.unit.is_ready
                and (trainer.unit.is_idle or not trainer.unit.is_structure)
        )
        )

        # return next(trainers_filtered, None)

        return min(
            trainers_filtered,
            key=lambda t: t.unit.tag,
            default=None
        )

    async def get_target_position(self, target: UnitTypeId) -> Point2:
        data = self.ai.game_data.units[target.value]
        if target in race_townhalls[self.ai.race]:
            for base in self.ai.resource_manager.bases:
                if base.townhall:
                    continue
                if base.position in self.ai.scout.blocked_positions:
                    continue
                if not base.remaining:
                    continue
                return base.position
            raise PlacementNotFoundException()

        bases = list(self.ai.resource_manager.bases)
        random.shuffle(bases)
        for base in bases:
            if not base.townhall:
                continue
            elif not base.townhall.unit.is_ready:
                continue
            position = base.position.towards_with_random_angle(base.mineral_patches.position, 10)
            offset = data.footprint_radius % 1
            position = position.rounded.offset((offset, offset))
            return position
        raise PlacementNotFoundException()

    def make_tech(self):
        upgrades = [
            u
            for unit in self.composition
            for u in self.ai.upgrades_by_unit(unit)
            if self.ai.strategy.filter_upgrade(u)
        ]
        targets = set(upgrades)
        targets.update(
            r
            for item in chain(self.composition, upgrades)
            for r in REQUIREMENTS[item]
        )
        for target in targets:
            if equivalents := WITH_TECH_EQUIVALENTS.get(target):
                target_met = any(self.ai.count(t) for t in equivalents)
            else:
                target_met = bool(self.ai.count(target))
            if not target_met:
                plan = self.add_plan(target)
                plan.priority = -1 / 3


class MacroBehavior(AIUnit):

    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)
        self.plan: Optional[MacroPlan] = None

    @property
    def macro_ability(self) -> Optional[AbilityId]:
        if (
                self.plan
                and (element := MACRO_INFO.get(self.unit.type_id))
                and (ability := element.get(self.plan.item))
        ):
            return ability.get('ability')
        else:
            return None

    def macro(self) -> Optional[UnitCommand]:

        if self.plan is None:
            return None
        elif not self.macro_ability:
            self.ai.macro.unassigned_plans.append(self.plan)
            self.plan = None
            # plan = self.ai.macro.add_plan(self.plan.item)
            # plan.priority = self.plan.priority
            # self.plan = None
            return None
        elif math.isinf(self.plan.eta):
            return None
        elif self.plan.eta <= 0.0:
            if self.unit.is_carrying_resource:
                return self.unit.return_resource()
            else:
                # if isinstance(self, GatherBehavior):
                #     self.gather_target = None
                return self.unit(self.macro_ability, target=self.plan.target)
        elif not self.plan.target:
            return None

        movement_eta = 1.2 * time_to_reach(self.unit, self.plan.target.position)
        if self.unit.is_carrying_resource:
            movement_eta += 3.0
        if self.plan.eta <= movement_eta:
            if self.plan.item == UnitTypeId.EXTRACTOR:
                return None
            elif self.unit.is_carrying_resource:
                return self.unit.return_resource()
            elif 1e-3 < self.unit.distance_to(self.plan.target.position):
                return self.unit.move(self.plan.target)
            else:
                return self.unit.hold_position()
        return None