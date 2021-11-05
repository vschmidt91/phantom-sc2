
from typing import Union, Iterable, Dict

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId

from .zerg_strategy import ZergStrategy
from ..observation import Observation

class ZergMacro(ZergStrategy):

    def composition(self, bot) -> Dict[UnitTypeId, int]:

        worker_limit = 80
        worker_target = min(worker_limit, bot.get_max_harvester())
        composition = {
            UnitTypeId.DRONE: worker_target,
            UnitTypeId.QUEEN: min(8, 2 * bot.townhalls.amount),
        }
        if 4 <= bot.townhalls.amount:
            composition[UnitTypeId.QUEEN] += 1
        worker_count = bot.observation.count(UnitTypeId.DRONE, include_planned=False)
        
        ratio = worker_count / worker_limit
    
        if bot.time < self.tech_time:
            composition[UnitTypeId.ZERGLING] = 6
        elif not bot.observation.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL2, include_planned=False):
            composition[UnitTypeId.OVERSEER] = 1
            composition[UnitTypeId.ROACH] = int(ratio * 50)
            composition[UnitTypeId.RAVAGER] = int(ratio * 10)
        elif not bot.observation.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL3, include_planned=False):
            composition[UnitTypeId.OVERSEER] = 2
            composition[UnitTypeId.ROACH] = 40
            composition[UnitTypeId.HYDRALISK] = 40
        else:
            composition[UnitTypeId.OVERSEER] = 3
            composition[UnitTypeId.ROACH] = 40
            composition[UnitTypeId.HYDRALISK] = 40
            composition[UnitTypeId.CORRUPTOR] = 3
            composition[UnitTypeId.BROODLORD] = 10

        return composition