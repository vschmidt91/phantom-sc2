
from __future__ import annotations
from typing import List, Union, Optional, Callable, TYPE_CHECKING

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.dicts.unit_research_abilities import RESEARCH_INFO
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO

from .cost import Cost

if TYPE_CHECKING:
    from .ai_base import AIBase

class MacroPlan:

    def __init__(self, item: Union[UnitTypeId, UpgradeId], **kwargs):
        self.item = item
        self.cost = None
        self.ability = None
        self.unit: Optional[int] = None
        self.target = None
        self.priority: float = 0
        self.max_distance: Optional[float] = None
        self.eta: Optional[float] = None
        self.condition: Callable[[AIBase], bool] = lambda b : True
        self.__dict__.update(**kwargs)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.item}, {self.ability}, {self.unit}, {self.target}, {self.priority})"

    def __hash__(self) -> int:
        return id(self)