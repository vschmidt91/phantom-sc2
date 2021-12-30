
from typing import Union, Iterable, Dict

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId


class ZergStrategy:

    def build_order(self) -> Iterable[Union[UnitTypeId, UpgradeId]]:
        return list()

    def gas_target(self, bot) -> int:
        return None

    def composition(self, bot) -> Dict[UnitTypeId, int]:
        return dict()

    def destroy_destructables(self, bot) -> bool:
        return False

    def filter_upgrade(self, upgrade) -> bool:
        return True

    def update(self, bot):
        pass

    def name(self) -> str:
        return type(self).__name__

    def steps(self, bot):
        return {}