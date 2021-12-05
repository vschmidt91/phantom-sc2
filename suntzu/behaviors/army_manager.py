

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
from suntzu.behaviors.burrow import BurrowBehavior

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

class ArmyManager(Behavior):

    def __init__(self, ai: AIBase):
        super().__init__()
        self.ai: AIBase = ai
        self.unit_tags: Set[int] = set()
        self.behaviors: Dict[int, UnitBehavior] = dict()

    def create_behavior(self, unit: Unit) -> UnitBehavior:
        behaviors = list()
        behaviors.append(DodgeBehavior(self.ai, unit.tag))
        if unit.type_id in { UnitTypeId.ROACH, UnitTypeId.ROACHBURROWED }:
            behaviors.append(BurrowBehavior(self.ai, unit.tag))
        if unit.type_id in { UnitTypeId.ROACH, UnitTypeId.ROACHBURROWED, UnitTypeId.RAVAGER, UnitTypeId.RAVAGERBURROWED }:
            behaviors.append(LaunchCorrosiveBilesBehavior(self.ai, unit.tag))
        if unit.type_id in { UnitTypeId.QUEEN, UnitTypeId.QUEENBURROWED }:
            behaviors.append(TransfuseBehavior(self.ai, unit.tag))
        behaviors.append(FightBehavior(self.ai, unit.tag))
        behaviors.append(SearchBehavior(self.ai, unit.tag))
        return BehaviorSelector(behaviors)

    def execute(self) -> BehaviorResult:

        for tag in self.unit_tags:
            unit = self.ai.unit_by_tag.get(tag)
            if not unit:
                self.unit_tags.remove(tag)
            behavior = self.behaviors.get(tag)
            if not behavior:
                behavior = self.create_behavior(unit)
                self.behaviors[unit.tag] = behavior
            behavior.execute()

        dead_tags = {
            tag for tag in self.behaviors.keys()
            if tag not in self.unit_tags
        }
        for tag in dead_tags:
            del self.behaviors[tag]

        return BehaviorResult.ONGOING