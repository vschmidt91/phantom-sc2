
from typing import Union, Iterable, Dict

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId

from ..observation import Observation

class ZergStrategy(object):

    @property
    def build_order(self) -> Iterable[Union[UnitTypeId, UpgradeId]]:
        return list()

    def composition(self, bot) -> Dict[UnitTypeId, int]:
        return dict()

    def destroy_destructables(self, bot) -> bool:
        return False

    @property
    def name(self) -> str:
        return type(self).__name__