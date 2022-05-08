
from __future__ import annotations
from typing import Optional, Set, Union, Iterable, Tuple, TYPE_CHECKING
import numpy as np
import random

from s2clientprotocol.common_pb2 import Point
from sc2.constants import SPEED_INCREASE_ON_CREEP_DICT

from sc2.position import Point2
from sc2.unit import Unit
from sc2.ids.buff_id import BuffId
from sc2.unit_command import UnitCommand
from sc2.data import race_worker
from abc import ABC, abstractmethod

from src.units.unit import CommandableUnit

from ..utils import *
from ..constants import *
from .behavior import Behavior
from ..ai_component import AIComponent
if TYPE_CHECKING:
    from ..ai_base import AIBase

class ExtractorTrickBehavior(CommandableUnit):
    
    def __init__(self, ai: AIBase, tag: int):
        super().__init__(ai, tag)

    def do_extractor_trick(self) -> Optional[UnitCommand]:

        if self.unit.type_id != UnitTypeId.EXTRACTOR:
            return None

        if self.unit.is_ready:
            return None

        if not self.ai.extractor_trick_enabled:
            return None

        if 0 < self.ai.supply_left:
            return None

        self.ai.extractor_trick_enabled = False
        return self.unit(AbilityId.CANCEL)