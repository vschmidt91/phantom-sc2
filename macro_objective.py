
from typing import List, Union

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.ids.upgrade_id import UpgradeId
from cost import Cost

from sc2.position import Point2
from sc2.dicts.unit_research_abilities import RESEARCH_INFO
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO

class MacroObjective(object):

    def __init__(self, item: Union[UnitTypeId, UpgradeId]):
        self.item = item
        self.ability = None
        self.cost = None
        self.unit = None
        self.target = None

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.item}, {self.ability}, {self.cost}, {self.unit}, {self.target})"
