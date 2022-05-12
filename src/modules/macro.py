

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

    def __init__(self, item: MacroId):
        self.item: MacroId = item
        self.target: Union[Unit, Point2] = None
        self.priority: float = 0.0
        self.max_distance: Optional[int] = 4
        self.eta: Optional[float] = None

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.item}, {self.target}, {self.priority}, {self.eta})"

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
            if any(self.ai.get_missing_requirements(unit)):
                continue
            priority = -self.ai.count(unit, include_planned=False) /  count
            for plan in self.planned_by_type(unit):
                if plan.priority == math.inf:
                    continue
                plan.priority = priority
                break
            else:
                plan = MacroPlan(unit)
                plan.priority = priority
                self.add_plan(plan)

    async def on_step(self) -> None:

        self.make_composition()

        reserve = Cost(0, 0, 0, 0)

        trainers = {
            behavior
            for behavior in self.ai.unit_manager.units.values()
            if (
                isinstance(behavior, MacroBehavior)
                and not behavior.plan
                and behavior.unit
            )
        }

        plans = sorted(
            self.enumerate_plans(),
            key = lambda t : t.priority,
            reverse=True
        )

        trainer_by_plan = {
            behavior.plan: behavior
            for behavior in self.ai.unit_manager.units.values()
            if isinstance(behavior, MacroBehavior) and behavior.plan
        }

        for i, plan in enumerate(plans):

            if (
                any(self.ai.get_missing_requirements(plan.item))
                and plan.priority == math.inf
            ):
                break

            if (2 if self.ai.extractor_trick_enabled else 1) <= i and plan.priority == math.inf:
                break

            if not (trainer := trainer_by_plan.get(plan)):
                if trainer := self.search_trainer(trainers, plan):
                    self.unassigned_plans.remove(plan)
                    trainer.plan = plan
                    trainers.remove(trainer)
                else:
                    continue
                
            if any(self.ai.get_missing_requirements(plan.item)):
                continue

            # if type(plan.item) == UnitTypeId:
            #     cost = self.ai.techtree.units[plan.item].cost
            # elif type(plan.item) == UpgradeId:
            #     cost = self.ai.techtree.upgrades[plan.item].cost2
            # else:
            #     raise TypeError()
            cost = self.ai.cost[plan.item]
            reserve += cost

            if plan.target == None:
                try:
                    plan.target = await self.get_target(trainer, plan)
                except PlacementNotFoundException as p: 
                    continue

            # if (
            #     plan.priority < math.inf
            #     and self.ai.is_structure(plan.item)
            #     and isinstance(plan.target, Point2)
            #     and not await self.ai.can_place_single(plan.item, plan.target)
            # ):
            #     self.remove_plan(plan)
            #     continue

            eta = None
            if not any(self.ai.get_missing_requirements(plan.item)):
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

    async def get_target(self, trainer: MacroBehavior, objective: MacroPlan) -> Coroutine[any, any, Union[Unit, Point2]]:
        gas_type = GAS_BY_RACE[self.ai.race]
        if objective.item == gas_type:
            exclude_positions = {
                geyser.position
                for geyser in self.ai.gas_buildings
            }
            exclude_tags = {
                order.target
                for unit in self.ai.unit_manager.pending_by_type[gas_type]
                if unit.unit
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
                
        # if isinstance(data.target, TechTreeAbilityTargetUnit) and data.target.type == TechTreeAbilityTargetUnitType.Build:
        if "requires_placement_position" in data:
            position = await self.get_target_position(objective.item)
            withAddon = objective in { UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT }
            
            if objective.max_distance != None:
                max_distance = objective.max_distance
                position = await self.ai.find_placement(trainer.macro_ability, position, max_distance=max_distance, placement_step=1, addon_place=withAddon)
            if position is None:
                raise PlacementNotFoundException()
            else:
                return position
        else:
            return None

    def search_trainer(self, trainers: Iterable[MacroBehavior], plan: MacroPlan) -> Optional[MacroBehavior]:

        if type(plan.item) == UnitTypeId:
            trainer_types = {
                equivalent
                for trainer in UNIT_TRAINED_FROM[plan.item]
                for equivalent in WITH_TECH_EQUIVALENTS[trainer]
            }
        elif type(plan.item) == UpgradeId:
            trainer_types = WITH_TECH_EQUIVALENTS[UPGRADE_RESEARCHED_FROM[plan.item]]

        trainers_filtered = (
            trainer
            for trainer in trainers
            if (
                trainer.unit.type_id in trainer_types
                and trainer.unit.is_ready
                and (trainer.unit.is_idle or not trainer.unit.is_structure)
            )
        )
        
        return next(trainers_filtered, None)

    async def get_target_position(self, target: UnitTypeId) -> Point2:
        data = self.ai.game_data.units[target.value]
        if target in race_townhalls[self.ai.race]:
            for b in self.ai.resource_manager.bases:
                if b.townhall:
                    continue
                if b.position in self.ai.scout.blocked_positions:
                    continue
                if not b.remaining:
                    continue
                return b.position
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

class MacroBehavior(CommandableUnit):
    
    def __init__(self, ai: AIBase, tag: int):
        super().__init__(ai, tag)
        self.plan: Optional[MacroPlan] = None

    @property
    def macro_ability(self) -> Optional[AbilityId]:
        if (
            self.unit
            and self.plan
            and (element := MACRO_INFO.get(self.unit.type_id))
            and (ability := element.get(self.plan.item))
        ):
            return ability.get('ability')
        else:
            return None

    def macro(self) -> Optional[UnitCommand]:

        if self.plan == None:
            return None
        elif not self.macro_ability:
            self.ai.macro.add_plan(self.plan)
            self.plan = None
            return None
        elif self.plan.eta == None:
            return None
        elif self.plan.eta == 0.0:
            if self.unit.is_carrying_resource:
                return self.unit.return_resource()
            else:
                # if isinstance(self, GatherBehavior):
                #     self.gather_target = None
                return self.unit(self.macro_ability, target=self.plan.target)
        elif not self.plan.target:
            return None

        movement_eta = 1.5 + time_to_reach(self.unit, self.plan.target.position)
        if self.unit.is_carrying_resource:
            movement_eta += 3.0
        if self.plan.eta < movement_eta:
            if self.unit.is_carrying_resource:
                return self.unit.return_resource()
            elif 1e-3 < self.unit.distance_to(self.plan.target.position):
                return self.unit.move(self.plan.target)
            else:
                return self.unit.hold_position()