
from typing import Union, Iterable, Dict

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId

from .hatch_first import HatchFirst

class BaneBust(HatchFirst):
    
    def composition(self, bot) -> Dict[UnitTypeId, int]:
        composition = super().composition(bot)
        return composition

    def update(self):
        self.ai.build_spines = False
        super().update()
        if self.ai.time < 5 * 60:
            self.ai.composition[UnitTypeId.BANELING] = 4
            self.ai.composition[UnitTypeId.ZERGLING] = 16

    def filter_upgrade(self, upgrade) -> bool:
        if self.ai.time < 5 * 60 and upgrade == UpgradeId.CENTRIFICALHOOKS:
            return False
        return super().filter_upgrade(upgrade)