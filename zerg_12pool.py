

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from bot_strategy import BotStrategy

class Zerg12Pool(BotStrategy):

    def __init__(self):
        super(self.__class__, self).__init__()

    async def on_step(self, bot, iteration):
        self.harvestGas = (
            not bot.already_pending_upgrade(UpgradeId.ZERGLINGMOVEMENTSPEED)
            and bot.vespene < 92
        )
        await bot.microQueens()
        bot.moveOverlord()
        self.destroyRocks = False

    def getTargets(self, bot):

        upgradeTargets = []
        if 80 <= bot.vespene:
            upgradeTargets.append(UpgradeId.ZERGLINGMOVEMENTSPEED)

        macroTargets = []

        if bot.count(UnitTypeId.SPAWNINGPOOL) < 1:
            macroTargets.append(UnitTypeId.SPAWNINGPOOL)

        # if (
        #     bot.count(UnitTypeId.EXTRACTOR) < 1
        #     and bot.structures(UnitTypeId.SPAWNINGPOOL).exists
        #     and 12 <= bot.supply_used
        # ):
        #     macroTargets.append(UnitTypeId.EXTRACTOR)

        if 14 == bot.supply_used and bot.count(UnitTypeId.OVERLORD) < 2:
            macroTargets.append(UnitTypeId.OVERLORD)
        elif 22 == bot.supply_used and bot.count(UnitTypeId.OVERLORD) < 3:
            macroTargets.append(UnitTypeId.OVERLORD)
        elif 22 < bot.supply_used and bot.count(UnitTypeId.OVERLORD) < bot.getSupplyTarget():
            macroTargets.append(UnitTypeId.OVERLORD)

        if bot.count(UnitTypeId.QUEEN) < min(5, bot.townhalls.amount):
            macroTargets.append(UnitTypeId.QUEEN)

        drone_target = 14 * min(3, bot.townhalls.amount)
        drone_target = max(14, drone_target)

        unitTarget = []
        if bot.supply_used < 14:
            unitTarget = [UnitTypeId.DRONE]
        elif bot.supply_used <= 22:
            unitTarget = [UnitTypeId.ZERGLING]
        elif bot.count(UnitTypeId.DRONE) < drone_target and bot.state.game_loop % 3 == 0:
            unitTarget = [UnitTypeId.DRONE]
        else:
            unitTarget = [UnitTypeId.ZERGLING]

        expandTarget = []
        if 19 <= bot.supply_used and bot.already_pending(UnitTypeId.HATCHERY) == 0:
            expandTarget.append(UnitTypeId.HATCHERY)

        return upgradeTargets + macroTargets + unitTarget + expandTarget