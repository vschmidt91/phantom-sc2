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
from .behavior import Behavior
from ..ai_component import AIComponent
if TYPE_CHECKING:
    from ..ai_base import AIBase

class MacroBehavior(Behavior):

    def __init__(self, ai: AIBase, unit_tag: int):
        super().__init__(ai, unit_tag)

    def execute_single(self, unit: Unit) -> Optional[UnitCommand]:

        plan = next((p for p in self.ai.macro_plans if p.unit == unit.tag), None)

        if plan == None:
            return None
        elif plan.ability == None:
            return None
        elif any(unit.orders) and unit.orders[0].ability.exact_id in ITEM_BY_ABILITY:
            return None
        # elif any(unit.orders) and unit.orders[0].ability.exact_id == plan.ability['ability']:
        #     return unit(plan.ability['ability'], target=unit.orders[0].target)
        elif plan.eta == None:
            return None
        elif not plan.condition(self.ai):
            return None
        elif plan.eta == 0.0:
            if unit.is_carrying_resource:
                return unit.return_resource()
            else:
                if unit.type_id == race_worker[self.ai.race]:
                    self.ai.bases.try_remove(unit.tag)
                    self.ai.unit_manager.drafted_civilians.difference_update([unit.tag])
                return unit(plan.ability['ability'], target=plan.target)
        elif not plan.target:
            return None

        movement_eta = 2 + time_to_reach(unit, plan.target.position)
        if plan.eta < movement_eta:
            if unit.is_carrying_resource:
                return unit.return_resource()
            elif 1e-3 < unit.position.distance_to(plan.target.position):
                return unit.move(plan.target.position)
            else:
                return unit.hold_position()