
from typing import Generic, Optional, Set, Union, Iterable, Tuple, List, TypeVar
import numpy as np
import random
from sc2.constants import SPEED_INCREASE_ON_CREEP_DICT

from sc2.position import Point2
from sc2.unit import Unit

from .unit_base import UnitBase
from ..utils import *
from ..constants import *

T = TypeVar('T', bound=UnitBase)

class UnitGroup(UnitBase, Generic[T], Iterable[T]):

    def __init__(self, units: Iterable[UnitBase]):
        self.units: List[UnitBase] = units

    def __iter__(self):
        return iter(self.units)

    def __getitem__(self, index):
        return self.units[index]

    def __len__(self):
        return len(self.units)

    def micro(self, **kwargs):
    
        for unit in self.units:
            unit.micro(**kwargs)