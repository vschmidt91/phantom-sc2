
from typing import Union, Iterable, Dict

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId

from ..observation import Observation

class ZergStrategy(object):

    def __init__(self):
        self.tech_time = 3.5 * 60

    def build_order(self) -> Iterable[Union[UnitTypeId, UpgradeId]]:
        return list()

    def gas_target(self, bot) -> int:
        return None

    def composition(self, bot) -> Dict[UnitTypeId, int]:
        return dict()

    def destroy_destructables(self, bot) -> bool:
        return False

    def update(self, bot):
        pass

    def name(self) -> str:
        return type(self).__name__