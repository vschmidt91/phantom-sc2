
from abc import ABC, abstractmethod
from reserve import Reserve

from sc2.ids.upgrade_id import UpgradeId

from typing import Coroutine, List, Union
from common import CommonAI
from sc2 import UnitTypeId

class BuildOrder(ABC):

    @abstractmethod
    def execute(self, bot: CommonAI) -> List[Union[UnitTypeId, UpgradeId]]:
        raise NotImplementedError()

class Pool12(BuildOrder):

    def execute(self, bot: CommonAI) -> List[Union[UnitTypeId, UpgradeId]]:

        if bot.count(UnitTypeId.SPAWNINGPOOL) < 1:
            return [UnitTypeId.SPAWNINGPOOL]
        elif bot.count(UnitTypeId.DRONE) < 14 and bot.count(UnitTypeId.HATCHERY) < 2:
            return [UnitTypeId.DRONE]
        elif bot.count(UnitTypeId.OVERLORD) < 2:
            return [UnitTypeId.OVERLORD]
        elif bot.count(UnitTypeId.QUEEN) < 1:
            return [UnitTypeId.QUEEN]
        elif bot.count(UnitTypeId.ZERGLING) < 10:
            return [UnitTypeId.ZERGLING]
        elif bot.count(UnitTypeId.HATCHERY) < 2:
            return [UnitTypeId.HATCHERY]
        elif bot.count(UnitTypeId.QUEEN) < 2:
            return [UnitTypeId.QUEEN]
        else:
            return None

class Pool16(BuildOrder):

    def execute(self, bot: CommonAI) -> List[Union[UnitTypeId, UpgradeId]]:
            
        if bot.count(UnitTypeId.DRONE) < 13:
            return [UnitTypeId.DRONE]
        elif bot.count(UnitTypeId.OVERLORD) < 2:
            return [UnitTypeId.OVERLORD]
        elif bot.count(UnitTypeId.DRONE) < 16:
            return [UnitTypeId.DRONE]
        elif bot.count(UnitTypeId.SPAWNINGPOOL) < 1:
            return [UnitTypeId.SPAWNINGPOOL]
        elif bot.count(UnitTypeId.DRONE) < 17:
            return [UnitTypeId.DRONE]
        elif bot.count(UnitTypeId.HATCHERY) < 2:
            return [UnitTypeId.HATCHERY]
        elif bot.count(UnitTypeId.DRONE) < 17:
            return [UnitTypeId.DRONE]
        elif bot.count(UnitTypeId.QUEEN) < 1:
            return [UnitTypeId.QUEEN]
        elif bot.count(UnitTypeId.ZERGLING) < 6:
            return [UnitTypeId.ZERGLING]
        elif bot.count(UnitTypeId.EXTRACTOR) < 1:
            return [UnitTypeId.EXTRACTOR]
        else:
            return None

class Hatch16(BuildOrder):

    def execute(self, bot: CommonAI) -> List[Union[UnitTypeId, UpgradeId]]:
            
        if bot.count(UnitTypeId.DRONE) < 13:
            return [UnitTypeId.DRONE]
        elif bot.count(UnitTypeId.OVERLORD) < 2:
            return [UnitTypeId.OVERLORD]
        elif bot.count(UnitTypeId.DRONE) < 16:
            return [UnitTypeId.DRONE]
        elif bot.count(UnitTypeId.HATCHERY) < 2:
            return [UnitTypeId.HATCHERY]
        elif bot.count(UnitTypeId.DRONE) < 18:
            return [UnitTypeId.DRONE]
        elif bot.count(UnitTypeId.EXTRACTOR) < 1:
            return [UnitTypeId.EXTRACTOR]
        elif bot.count(UnitTypeId.SPAWNINGPOOL) < 1:
            return [UnitTypeId.SPAWNINGPOOL]
        else:
            return None