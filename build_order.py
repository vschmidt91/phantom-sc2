
from abc import ABC, abstractmethod
from reserve import Reserve

from sc2.ids.upgrade_id import UpgradeId


from common import CommonAI
from sc2 import UnitTypeId

class BuildOrder(ABC):

    @abstractmethod
    def execute(self, bot: CommonAI, reserve: Reserve):
        raise NotImplementedError()

class Pool12(BuildOrder):

    async def execute(self, bot, reserve):

        if bot.count(UnitTypeId.SPAWNINGPOOL) < 1:
            reserve = await bot.train(UnitTypeId.SPAWNINGPOOL, reserve)
        elif bot.count(UnitTypeId.DRONE) < 14 and bot.count(UnitTypeId.HATCHERY) < 2:
            reserve = await bot.train(UnitTypeId.DRONE, reserve)
        elif bot.count(UnitTypeId.OVERLORD) < 2:
            reserve = await bot.train(UnitTypeId.OVERLORD, reserve)
        elif bot.count(UnitTypeId.QUEEN) < 1:
            reserve = await bot.train(UnitTypeId.QUEEN, reserve)
        elif bot.count(UnitTypeId.ZERGLING) < 10:
            reserve = await bot.train(UnitTypeId.ZERGLING, reserve)
        elif bot.count(UnitTypeId.HATCHERY) < 2:
            reserve = await bot.train(UnitTypeId.HATCHERY, reserve)
        elif bot.count(UnitTypeId.QUEEN) < 2:
            reserve = await bot.train(UnitTypeId.QUEEN, reserve)
        else:
            bot.buildOrder = None

        return reserve

class Pool16(BuildOrder):

    async def execute(self, bot, reserve):
            
        if bot.count(UnitTypeId.DRONE) < 13:
            reserve = await bot.train(UnitTypeId.DRONE, reserve)
        elif bot.count(UnitTypeId.OVERLORD) < 2:
            reserve = await bot.train(UnitTypeId.OVERLORD, reserve)
        elif bot.count(UnitTypeId.DRONE) < 16:
            reserve = await bot.train(UnitTypeId.DRONE, reserve)
        elif bot.count(UnitTypeId.SPAWNINGPOOL) < 1:
            reserve = await bot.train(UnitTypeId.SPAWNINGPOOL, reserve)
        elif bot.count(UnitTypeId.DRONE) < 17 and bot.count(UnitTypeId.EXTRACTOR) < 1:
            reserve = await bot.train(UnitTypeId.DRONE, reserve)
        elif bot.count(UnitTypeId.HATCHERY) < 2:
            reserve = await bot.train(UnitTypeId.HATCHERY, reserve)
        elif bot.count(UnitTypeId.QUEEN) < 1:
            reserve = await bot.train(UnitTypeId.QUEEN, reserve)
        elif bot.count(UnitTypeId.ZERGLING) < 6:
            reserve = await bot.train(UnitTypeId.ZERGLING, reserve)
        elif bot.count(UnitTypeId.EXTRACTOR) < 1:
            reserve = await bot.train(UnitTypeId.EXTRACTOR, reserve)
        elif bot.structures(UnitTypeId.EXTRACTOR).exists:
            bot.buildOrder = None

        return reserve

class Hatch16(BuildOrder):

    async def execute(self, bot, reserve):
            
        if bot.count(UnitTypeId.DRONE) < 13:
            reserve = await bot.train(UnitTypeId.DRONE, reserve)
        elif bot.count(UnitTypeId.OVERLORD) < 2:
            reserve = await bot.train(UnitTypeId.OVERLORD, reserve)
        elif bot.count(UnitTypeId.DRONE) < 16:
            reserve = await bot.train(UnitTypeId.DRONE, reserve)
        elif bot.count(UnitTypeId.HATCHERY) < 2:
            reserve = await bot.train(UnitTypeId.HATCHERY, reserve)
        elif bot.count(UnitTypeId.DRONE) < 18:
            reserve = await bot.train(UnitTypeId.DRONE, reserve)
        elif bot.count(UnitTypeId.EXTRACTOR) < 1:
            reserve = await bot.train(UnitTypeId.EXTRACTOR, reserve)
        elif bot.count(UnitTypeId.SPAWNINGPOOL) < 1:
            reserve = await bot.train(UnitTypeId.SPAWNINGPOOL, reserve)
        elif bot.structures(UnitTypeId.SPAWNINGPOOL).exists:
            bot.buildOrder = None

        return reserve