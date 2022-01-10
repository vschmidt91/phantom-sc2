from __future__ import annotations
from typing import Optional, Set, Union, Iterable, Tuple, TYPE_CHECKING
import numpy as np
import random
from sc2.constants import SPEED_INCREASE_ON_CREEP_DICT
from sc2.ids.buff_id import BuffId

from sc2.position import Point2
from sc2.unit import Unit
from sc2.unit_command import UnitCommand
from sc2.data import race_worker
from abc import ABC, abstractmethod

from ..utils import *
from ..constants import *
from .behavior import Behavior, BehaviorResult, UnitBehavior
from ..ai_component import AIComponent
if TYPE_CHECKING:
    from ..ai_base import AIBase

class MacroBehavior(UnitBehavior):

    def __init__(self, ai: AIBase, unit_tag: int):
        super().__init__(ai, unit_tag)

    def execute_single(self, unit: Unit) -> BehaviorResult:

        for order in unit.orders:
            if order.ability.exact_id in ITEM_BY_ABILITY:
                return BehaviorResult.ONGOING

        plan = next((p for p in self.ai.macro_plans if p.unit == unit.tag), None)

        if plan == None:
            return BehaviorResult.SUCCESS
        elif plan.ability == None:
            return BehaviorResult.SUCCESS
        elif unit.is_using_ability(plan.ability['ability']):
            return BehaviorResult.ONGOING
        elif plan.eta == None:
            return BehaviorResult.SUCCESS
        elif not plan.condition(self.ai):
            return BehaviorResult.SUCCESS
        elif plan.eta == 0.0:
            if unit.is_carrying_resource:
                unit.return_resource()
            else:
                if unit.type_id == race_worker[self.ai.race]:
                    self.ai.bases.try_remove(unit.tag)
                    self.ai.unit_manager.drafted_civilians.difference_update([unit.tag])
                unit(plan.ability['ability'], target=plan.target, subtract_cost=True)
                # print(plan)
            return BehaviorResult.ONGOING
        elif not plan.target:
            return BehaviorResult.SUCCESS

        movement_eta = 2 + time_to_reach(unit, plan.target.position)
        if plan.eta < movement_eta:
            if unit.is_carrying_resource:
                unit.return_resource()
            elif not unit.is_moving and 1 < unit.position.distance_to(plan.target.position):
                unit.move(plan.target)
            return BehaviorResult.ONGOING
            
        return BehaviorResult.SUCCESS
