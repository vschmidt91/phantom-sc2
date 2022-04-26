from __future__ import annotations
from typing import Optional, Set, Union, Iterable, Tuple, TYPE_CHECKING
import numpy as np
import random
from sc2.constants import SPEED_INCREASE_ON_CREEP_DICT

from sc2.position import Point2
from sc2.unit import Unit
from sc2.unit_command import UnitCommand
from sc2.data import race_worker
from abc import ABC, abstractmethod

from ..units.unit import AIUnit

from ..utils import *
from ..constants import *
from .behavior import Behavior
from ..ai_component import AIComponent
if TYPE_CHECKING:
    from ..ai_base import AIBase

class CancelBehavior(AIUnit):

    def __init__(self, ai: AIBase, tag: int):
        super().__init__(ai, tag)

    def cancel(self) -> Optional[UnitCommand]:

        if self.unit.is_ready:
            return None