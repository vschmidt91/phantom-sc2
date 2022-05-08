

from __future__ import annotations
from ctypes.wintypes import tagMSG
from typing import Callable, Coroutine, DefaultDict, Optional, Set, Union, Iterable, Tuple, List, TYPE_CHECKING
import random
import logging

from numpy import isin

from sc2.position import Point2
from sc2.unit import Unit
from sc2.unit_command import UnitCommand
from sc2.data import race_worker, race_townhalls
from src.ai_component import AIComponent
from src.behaviors.gather import GatherBehavior
from src.techtree import TechTreeAbilityTarget, TechTreeAbilityTargetUnit, TechTreeAbilityTargetUnitType
from src.units.unit import CommandableUnit

from ..cost import Cost
from ..utils import *
from ..constants import *
from .module import AIModule
from ..behaviors.behavior import Behavior
if TYPE_CHECKING:
    from ..ai_base import AIBase, PlacementNotFoundException

MacroId = Union[UnitTypeId, UpgradeId]

class MacroPlan:

    def __init__(self, item: MacroId, **kwargs):
        self.item: MacroId = item
        self.ability: Optional[AbilityId] = None
        self.target: Union[Unit, Point2] = None
        self.priority: float = 0.0
        self.max_distance: Optional[int] = 4
        self.eta: Optional[float] = None
        self.__dict__.update(**kwargs)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.item}, {self.ability}, {self.target}, {self.priority}, {self.eta})"

    def __hash__(self) -> int:
        return id(self)

class MacroModule(AIModule):

    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)
        self.unassigned_plans: List[MacroPlan] = list()

    def add_plan(self, plan: MacroPlan) -> None:
        self.unassigned_plans.append(plan)
        
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
            for unit in self.ai.composition.keys()
        }
        for unit, count in self.ai.composition.items():
            if count < 1:
                continue
            elif count <= composition_have[unit]:
                continue
            if any(self.ai.get_missing_requirements(unit, include_pending=False, include_planned=False)):
                continue
            priority = -self.ai.count(unit, include_planned=False) /  count
            for plan in self.planned_by_type(unit):
                if BUILD_ORDER_PRIORITY <= plan.priority:
                    continue
                plan.priority = priority
                break
            else:
                self.add_plan(MacroPlan(unit, priority=priority))

    async def on_step(self) -> None:

        self.make_composition()

        reserve = Cost(0, 0, 0, 0)
        exclude = {
            tag
            for tag, behavior in self.ai.unit_manager.units.items()
            if isinstance(behavior, MacroBehavior) and behavior.plan
        }
        exclude.update(unit.tag for units in self.ai.pending_by_type.values() for unit in units)

        trainers = {
            tag
            for tag, behavior in self.ai.unit_manager.units.items()
            if isinstance(behavior, MacroBehavior) and not behavior.plan
        }

        plans = sorted(self.enumerate_plans(), key = lambda t : t.priority, reverse=True)

        unit_by_plan = {
            behavior.plan: tag
            for tag, behavior in self.ai.unit_manager.units.items()
            if isinstance(behavior, MacroBehavior)
        }

        for i, plan in enumerate(plans):

            if (
                any(self.ai.get_missing_requirements(plan.item, include_pending=False, include_planned=False))
                and plan.priority == BUILD_ORDER_PRIORITY
            ):
                break

            if (2 if self.ai.extractor_trick_enabled else 1) <= i and plan.priority == BUILD_ORDER_PRIORITY:
                break

            if unit_tag := unit_by_plan.get(plan):
                unit = self.ai.unit_manager.unit_by_tag.get(unit_tag)
            else:
                unit = None

            if unit == None:
                unit, plan.ability = self.search_trainer(plan.item, include=trainers)
            if unit and plan.ability and unit.is_using_ability(plan.ability):
                continue
            if unit == None:
                continue
            if any(self.ai.get_missing_requirements(plan.item, include_pending=False, include_planned=False)):
                continue

            cost = self.ai.cost[plan.item]
            reserve += cost

            behavior = self.ai.unit_manager.units.get(unit.tag)
            if not behavior.plan:
                if plan in self.unassigned_plans:
                    self.unassigned_plans.remove(plan)
                behavior.plan = plan
                exclude.add(unit.tag)

            if unit.type_id == UnitTypeId.EGG:
                behavior.plan = None
                self.unassigned_plans.append(plan)
                continue

            if plan.target == None:
                try:
                    plan.target = await self.get_target(unit, plan)
                except PlacementNotFoundException as p: 
                    continue

            # if (
            #     plan.priority < BUILD_ORDER_PRIORITY
            #     and self.ai.is_structure(plan.item)
            #     and isinstance(plan.target, Point2)
            #     and not await self.ai.can_place_single(plan.item, plan.target)
            # ):
            #     self.remove_plan(plan)
            #     continue

            eta = None
            if not any(self.ai.get_missing_requirements(plan.item, include_pending=False, include_planned=False)):
                eta = 0
                if 0 < cost.minerals:
                    eta = max(eta, 60 * (reserve.minerals - self.ai.minerals) / max(1, self.ai.income.minerals))
                if 0 < cost.vespene:
                    eta = max(eta, 60 * (reserve.vespene - self.ai.vespene) / max(1, self.ai.income.vespene))
                if 0 < cost.larva:
                    eta = max(eta, 60 * (reserve.larva - self.ai.larva.amount) / max(1, self.ai.income.larva))
                if 0 < cost.food:
                    if self.ai.supply_left < cost.food:
                        eta = None
            plan.eta = eta

    async def get_target(self, unit: Unit, objective: MacroPlan) -> Coroutine[any, any, Union[Unit, Point2]]:
        gas_type = GAS_BY_RACE[self.ai.race]
        if objective.item == gas_type:
            exclude_positions = {
                geyser.position
                for geyser in self.ai.gas_buildings
            }
            exclude_tags = {
                order.target
                for trainer in self.ai.pending_by_type[gas_type]
                for order in trainer.orders
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

        if type(objective.item) is UnitTypeId:
            table = TRAIN_INFO
        elif type(objective.item) is UpgradeId:
            table = RESEARCH_INFO
        else:
            table = {}
        data = table[unit.type_id][objective.item]
                
        # if isinstance(data.target, TechTreeAbilityTargetUnit) and data.target.type == TechTreeAbilityTargetUnitType.Build:
        if "requires_placement_position" in data:
            position = await self.get_target_position(objective.item, unit)
            withAddon = objective in { UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT }
            
            if objective.max_distance != None:
                max_distance = objective.max_distance
                position = await self.ai.find_placement(objective.ability, position, max_distance=max_distance, placement_step=1, addon_place=withAddon)
            if position is None:
                raise PlacementNotFoundException()
            else:
                return position
        else:
            return None

    def search_trainer(self, item: Union[UnitTypeId, UpgradeId], include: Set[int]) -> Tuple[Unit, AbilityId]:

        if type(item) == UnitTypeId:
            trainer_types = {
                equivalent
                for trainer in UNIT_TRAINED_FROM[item]
                for equivalent in WITH_TECH_EQUIVALENTS[trainer]
            }
        elif type(item) == UpgradeId:
            trainer_types = WITH_TECH_EQUIVALENTS[UPGRADE_RESEARCHED_FROM[item]]

        trainers = sorted((
            trainer
            for trainer_type in trainer_types
            for trainer in self.ai.actual_by_type[trainer_type]
            if trainer.type_id != UnitTypeId.EGG
        ), key=lambda t:t.tag)
            
        for trainer in trainers:

            if not trainer:
                continue

            if not trainer.is_ready:
                continue

            if trainer.tag not in include:
                continue

            # if trainer.tag in exclude:
            #     continue

            if not has_capacity(trainer):
                continue

            already_training = False
            for order in trainer.orders:
                order_unit = UNIT_BY_TRAIN_ABILITY.get(order.ability.id)
                if order_unit:
                    already_training = True
                    break
            if already_training:
                continue

            if type(item) is UnitTypeId:
                table = TRAIN_INFO
            elif type(item) is UpgradeId:
                table = RESEARCH_INFO

            element = table.get(trainer.type_id)
            if not element:
                continue

            ability = element.get(item)

            if not ability:
                continue

            if "requires_techlab" in ability and not trainer.has_techlab:
                continue
                
            return trainer, ability['ability']

        return None, None

    async def get_target_position(self, target: UnitTypeId, trainer: Unit) -> Point2:
        data = self.ai.game_data.units[target.value]
        if target in race_townhalls[self.ai.race]:
            for b in self.ai.resource_manager.bases:
                if b.townhall:
                    continue
                # if b.position in self.ai.scout_manager.blocked_positions:
                #     continue
                if not b.remaining:
                    continue
                return b.position
            raise PlacementNotFoundException()

        bases = list(self.ai.resource_manager.bases)
        random.shuffle(bases)
        for base in bases:
            if not base.townhall:
                continue
            elif not base.townhall.is_ready:
                continue
            position = base.position.towards_with_random_angle(base.mineral_patches.position, 10)
            offset = data.footprint_radius % 1
            position = position.rounded.offset((offset, offset))
            return position
        raise PlacementNotFoundException()

class MacroBehavior(CommandableUnit):
    
    def __init__(self, ai: AIBase, tag: int):
        super().__init__(ai, tag)
        self.plan: Optional[MacroPlan] = None

    def macro(self) -> Optional[UnitCommand]:

        if self.plan == None:
            return None
        elif self.plan.ability == None:
            return None
        elif self.plan.eta == None:
            return None
        elif self.plan.eta == 0.0:
            if self.unit.is_carrying_resource:
                return self.unit.return_resource()
            else:
                if isinstance(self, GatherBehavior):
                    self.gather_target = None
                command = self.unit(self.plan.ability, target=self.plan.target)
                # self.plan = None
                return command
        elif not self.plan.target:
            return None

        movement_eta = 1.5 + time_to_reach(self.unit, self.plan.target.position)
        if self.unit.is_carrying_resource:
            movement_eta += 3.0
        if self.plan.eta < movement_eta:
            if self.unit.is_carrying_resource:
                return self.unit.return_resource()
            elif 1e-3 < self.unit.distance_to(self.plan.target.position):
                return self.unit.move(self.plan.target.position)
            else:
                return self.unit.hold_position()