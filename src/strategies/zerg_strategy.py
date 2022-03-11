
from __future__ import annotations
from typing import Union, Iterable, Dict, TYPE_CHECKING

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId
from ..ai_component import AIComponent

from ..ai_base import AIBase

class ZergStrategy(AIComponent):

    def __init__(self, ai: AIBase):
        super().__init__(ai)

    def build_order(self) -> Iterable[Union[UnitTypeId, UpgradeId]]:
        return list()

    def composition(self) -> Dict[UnitTypeId, int]:
        return dict()

    def destroy_destructables(self) -> bool:
        return False

    def filter_upgrade(self, upgrade: UpgradeId) -> bool:
        return True

    def update(self):
        pass

    @property
    def name(self) -> str:
        return type(self).__name__

    def steps(self):
        return {}