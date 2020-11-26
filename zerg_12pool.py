

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from bot_strategy import BotStrategy

class Zerg12Pool(BotStrategy):

    def __init__(self):
        super(self.__class__, self).__init__()

    async def on_start(self, bot):
        self.destroyRocks = False

    async def on_step(self, bot, iteration):
        await bot.microQueens()
        bot.moveOverlord()

    def getTargets(self, bot):

        targets = []

        if bot.count(UnitTypeId.SPAWNINGPOOL) < 1:
            targets.append(UnitTypeId.SPAWNINGPOOL)

        if bot.count(UnitTypeId.OVERLORD) < bot.getSupplyTarget():
            if 14 == bot.supply_used:
                targets.append(UnitTypeId.OVERLORD)
            elif 22 == bot.supply_used and 2 <= bot.townhalls.amount:
                targets.append(UnitTypeId.OVERLORD)
            elif 22 < bot.supply_used:
                targets.append(UnitTypeId.OVERLORD)

        if bot.count(UnitTypeId.QUEEN) < min(5, bot.townhalls.amount):
            targets.append(UnitTypeId.QUEEN)

        if bot.supply_used < 14:
            targets.append(UnitTypeId.DRONE)
        elif bot.supply_used < 21:
            targets.append(UnitTypeId.ZERGLING)

        if 1 <= bot.count(UnitTypeId.QUEEN):
            targets.append(UnitTypeId.HATCHERY)

        return targets