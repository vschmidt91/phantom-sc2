
from abc import ABC, abstractmethod

from sc2.ids.upgrade_id import UpgradeId


from common import CommonAI
from sc2 import UnitTypeId

class BuildOrder(ABC):

    @abstractmethod
    def getTargets(self, bot):
        raise NotImplementedError()

class Pool12(BuildOrder):

    def getTargets(self, bot: CommonAI):

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

        return None

class Pool16(BuildOrder):

    def getTargets(self, bot: CommonAI):
            
        if bot.count(UnitTypeId.DRONE) < 13:
            return [UnitTypeId.DRONE]
        elif bot.count(UnitTypeId.OVERLORD) < 2:
            return [UnitTypeId.OVERLORD]
        elif bot.count(UnitTypeId.DRONE) < 16:
            return [UnitTypeId.DRONE]
        elif bot.count(UnitTypeId.SPAWNINGPOOL) < 1:
            return [UnitTypeId.SPAWNINGPOOL]
        elif bot.count(UnitTypeId.DRONE) < 17 and bot.count(UnitTypeId.EXTRACTOR) < 1:
            return [UnitTypeId.DRONE]
        elif bot.count(UnitTypeId.HATCHERY) < 2:
            return [UnitTypeId.HATCHERY]
        elif bot.count(UnitTypeId.QUEEN) < 1:
            return [UnitTypeId.QUEEN]
        elif bot.count(UnitTypeId.ZERGLING) < 6:
            return [UnitTypeId.ZERGLING]
        elif bot.count(UnitTypeId.EXTRACTOR) < 1:
            return [UnitTypeId.EXTRACTOR]

        return None

class Hatch16(BuildOrder):

    def getTargets(self, bot: CommonAI):
            
        if bot.count(UnitTypeId.DRONE) < 13:
            return [UnitTypeId.DRONE]
        elif bot.count(UnitTypeId.OVERLORD) < 2:
            return [UnitTypeId.OVERLORD]
        if bot.count(UnitTypeId.DRONE) < 16:
            return [UnitTypeId.DRONE]
        elif bot.count(UnitTypeId.HATCHERY) < 2:
            return [UnitTypeId.HATCHERY]
        if bot.count(UnitTypeId.DRONE) < 18:
            return [UnitTypeId.DRONE]
        elif bot.count(UnitTypeId.EXTRACTOR) < 1:
            bot.gasTarget = 3
            return [UnitTypeId.EXTRACTOR]
        elif bot.count(UnitTypeId.SPAWNINGPOOL) < 1:
            return [UnitTypeId.SPAWNINGPOOL]
        elif bot.count(UnitTypeId.DRONE) < 18:
            return [UnitTypeId.DRONE]
        elif bot.count(UnitTypeId.OVERLORD) < 3:
            return [UnitTypeId.OVERLORD]
        elif not bot.structures(UnitTypeId.SPAWNINGPOOL).ready.exists:
            bot.gasTarget = 3
            return []

        return None