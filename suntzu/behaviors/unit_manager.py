

from __future__ import annotations
from typing import DefaultDict, Optional, Set, Union, Iterable, Tuple, TYPE_CHECKING
from enum import Enum
import numpy as np
import random
from sc2.constants import SPEED_INCREASE_ON_CREEP_DICT

from sc2.position import Point2
from sc2.unit import Unit
from sc2.unit_command import UnitCommand
from sc2.data import race_worker
from abc import ABC, abstractmethod
from suntzu.behaviors.army_manager import ArmyManager
from suntzu.behaviors.burrow import BurrowBehavior
from suntzu.behaviors.creep_manager import CreepManager

from suntzu.behaviors.dodge import DodgeBehavior
from suntzu.behaviors.fight import FightBehavior
from suntzu.behaviors.launch_corrosive_biles import LaunchCorrosiveBilesBehavior
from suntzu.behaviors.search import SearchBehavior
from suntzu.behaviors.transfuse import TransfuseBehavior

from ..utils import *
from ..constants import *
from .behavior import Behavior, BehaviorResult, BehaviorSelector, BehaviorSequence, UnitBehavior
from ..ai_component import AIComponent
if TYPE_CHECKING:
    from ..ai_base import AIBase

class UnitManager(Behavior):

    def __init__(self, ai: AIBase):
        super().__init__()
        self.ai: AIBase = ai
        self.army_manager = ArmyManager(ai)
        self.creep_manager = CreepManager(ai)
        self.drafted_civilians: Set[int] = set()

    def draft_civilians(self):

        self.drafted_civilians = {
            u for u in self.drafted_civilians
            if u in self.ai.unit_by_tag
        }
        
        if (
            2/3 < self.ai.threat_level
            and self.ai.time < 3 * 60
        ):
            worker = self.ai.bases.try_remove_any()
            if worker:
                self.drafted_civilians.add(worker)
        elif self.ai.threat_level < 1/3:
            if self.drafted_civilians:
                worker = self.drafted_civilians.pop()
                if not self.ai.bases.try_add(worker):
                    self.drafted_civilians.add(worker)

    def execute(self) -> BehaviorResult:

        self.draft_civilians()

        queens = sorted(
            self.ai.actual_by_type[UnitTypeId.QUEEN],
            key = lambda q : self.ai.distance_map[q.position.rounded]
        )

        inject_queen_count = min(3, len(queens), self.ai.townhalls.amount)
        creep_queen_count = 1 if max(inject_queen_count, 2) < len(queens) else 0

        inject_queens = queens[0:inject_queen_count]
        creep_queens = queens[inject_queen_count:inject_queen_count+creep_queen_count]

        self.creep_manager.queens = { q.tag for q in creep_queens }

        bases = [
            b
            for b in self.ai.bases
            if b.position in self.ai.townhall_by_position
        ]
        for queen, base in zip(inject_queens, bases):
            townhall = self.ai.townhall_by_position[base.position]
            if not townhall:
                continue
            if 7 < queen.position.distance_to(townhall.position):
                queen.attack(townhall.position)
            elif 25 <= queen.energy:
                queen(AbilityId.EFFECT_INJECTLARVA, townhall)

        self.army_manager.unit_tags.clear()
        for unit in self.ai.units:
            
            if unit.type_id == UnitTypeId.QUEEN:
                exclude_abilities = {
                    AbilityId.BUILD_CREEPTUMOR_QUEEN,
                    AbilityId.EFFECT_INJECTLARVA,
                    AbilityId.TRANSFUSION_TRANSFUSION,
                }
                order_abilities = {
                    o.ability.exact_id
                    for o in unit.orders
                }
                if unit in creep_queens:
                    pass
                elif unit in inject_queens:
                    pass
                elif order_abilities.intersection(exclude_abilities):
                    pass
                else:
                    self.army_manager.unit_tags.add(unit.tag)
            elif unit.type_id == UnitTypeId.OVERSEER:
                if unit.tag in self.ai.blocked_base_detectors.values():
                    pass
                else:
                    self.army_manager.unit_tags.add(unit.tag)
            elif unit.type_id not in CIVILIANS:
                self.army_manager.unit_tags.add(unit.tag)
            elif unit.tag in self.drafted_civilians:
                self.army_manager.unit_tags.add(unit.tag)
            else:
                pass

        self.army_manager.execute()
        self.creep_manager.execute()

        return BehaviorResult.ONGOING