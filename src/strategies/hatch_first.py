
from typing import Union, Iterable, Dict

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId

from .zerg_macro import ZergMacro
from .zerg_strategy import ZergStrategy

class HatchFirst(ZergMacro):

    def __init__(self):
        super().__init__()
        self.tech_time = 3.75 * 60

    def build_order(self) -> Iterable[Union[UnitTypeId, UpgradeId]]:
        return [
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.EXTRACTOR,
            UnitTypeId.OVERLORD,
            UnitTypeId.HATCHERY,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.DRONE,
            UnitTypeId.EXTRACTOR,
            UnitTypeId.SPAWNINGPOOL,
            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
            # UnitTypeId.OVERLORD,
            # UnitTypeId.DRONE,
            # UnitTypeId.DRONE,
            # UnitTypeId.OVERLORD,
        ]

    def update(self, bot):
        if bot.supply_used == 14:
            bot.extractor_trick_enabled = True
        return super().update(bot)