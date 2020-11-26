

from sc2.bot_ai import BotAI
from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from bot_strategy import BotStrategy
from utils import armyValue, filterArmy

class ZergMacro(BotStrategy):

    def __init__(self):
        super(self.__class__, self).__init__()
        
    async def on_step(self, bot, iteration):
        self.destroyRocks = 50 <= bot.supply_used
        await bot.microQueens()
        bot.moveOverlord()
        # self.harvestGas = not bot.already_pending(UpgradeId.ZERGLINGMOVEMENTSPEED) or (UpgradeId.ZERGLINGMOVEMENTSPEED in bot.state.upgrades and 3 <= bot.townhalls.amount)
        self.harvestGas = 3 <= bot.townhalls.amount
        await bot.changelingScout()

    def getTargets(self, bot):

        armyRatio = (1 + armyValue(filterArmy(bot.units))) / (1 + armyValue(filterArmy(bot.enemy_units)))

        upgradeTargets = []
        
        if 22 <= bot.supply_used:
            
            upgradeTargets += [
                # UpgradeId.ZERGLINGMOVEMENTSPEED,
                UpgradeId.GLIALRECONSTITUTION,
                # UpgradeId.CENTRIFICALHOOKS,
                UpgradeId.EVOLVEGROOVEDSPINES]

            if .5 < armyRatio:
                upgradeTargets += [
                    UpgradeId.EVOLVEMUSCULARAUGMENTS,
                    # UpgradeId.ZERGLINGATTACKSPEED,

                    UpgradeId.ZERGMISSILEWEAPONSLEVEL1,
                    UpgradeId.ZERGMISSILEWEAPONSLEVEL2,
                    UpgradeId.ZERGMISSILEWEAPONSLEVEL3,

                    UpgradeId.ZERGGROUNDARMORSLEVEL1,
                    UpgradeId.ZERGGROUNDARMORSLEVEL2,
                    UpgradeId.ZERGGROUNDARMORSLEVEL3,

                    # UpgradeId.ZERGMELEEWEAPONSLEVEL1,
                    # UpgradeId.ZERGMELEEWEAPONSLEVEL2,
                    # UpgradeId.ZERGMELEEWEAPONSLEVEL3,

                    # UpgradeId.ZERGFLYERWEAPONSLEVEL1,
                    # UpgradeId.ZERGFLYERARMORSLEVEL1,
                    # UpgradeId.ZERGFLYERWEAPONSLEVEL2,
                    # UpgradeId.ZERGFLYERARMORSLEVEL2,
                    # UpgradeId.ZERGFLYERWEAPONSLEVEL3,
                    # UpgradeId.ZERGFLYERARMORSLEVEL3,
                ]

        if 4 <= bot.townhalls.amount:
            upgradeTargets.append(UpgradeId.OVERLORDSPEED)

        workers_target = bot.getMaxWorkers()
        workers_target = min(62, workers_target)
        workers_target = max(17, workers_target)
        
        if bot.supply_used < 17 or not self.harvestGas:
            gas_target = 0
        # elif 2 == bot.townhalls.amount:
        #     gas_target = 1
        # elif 3 <= bot.townhalls.amount:
        #     gas_target = 3
        else:
            gas_target = bot.gas_buildings.filter(lambda g: not g.has_vespene).amount + min(8, 2 * bot.townhalls.ready.amount - 2)


        macroTargets = []
        
        if 17 <= bot.supply_used and bot.count(UnitTypeId.SPAWNINGPOOL) == 0:
            macroTargets.append(UnitTypeId.SPAWNINGPOOL)

        if bot.already_pending(UnitTypeId.EXTRACTOR) < 1 and bot.count(UnitTypeId.EXTRACTOR) < gas_target:
            macroTargets.append(UnitTypeId.EXTRACTOR)

        if bot.count(UnitTypeId.QUEEN) < min(4, bot.townhalls.amount):
            macroTargets.append(UnitTypeId.QUEEN)

        if bot.count(UnitTypeId.OVERSEER) < 1:
            macroTargets.append(UnitTypeId.OVERSEER)

        if bot.enemy_race == Race.Zerg:
            sporeTime = 8 * 60
        else:
            sporeTime = 4 * 60

        if sporeTime <= bot.time and bot.already_pending(UnitTypeId.SPORECRAWLER) == 0:

            if bot.count(UnitTypeId.SPORECRAWLER) < bot.townhalls.amount:
                macroTargets.append(UnitTypeId.SPORECRAWLER)
            elif 1.1 * workers_target < bot.count(UnitTypeId.DRONE):
                macroTargets.append(UnitTypeId.SPORECRAWLER)

        if (
            22 <= bot.count(UnitTypeId.DRONE)
            and 2 <= bot.townhalls.ready.amount
            and 3 <= bot.townhalls.amount
        ):
            if bot.count(UnitTypeId.ROACHWARREN) < 1:
                macroTargets.append(UnitTypeId.ROACHWARREN)
            elif bot.count(UnitTypeId.LAIR) + bot.count(UnitTypeId.HIVE) < 1:
                macroTargets.append(UnitTypeId.LAIR)
            elif bot.count(UnitTypeId.EVOLUTIONCHAMBER) < 1:
                macroTargets.append(UnitTypeId.EVOLUTIONCHAMBER)
            

        if (
            44 <= bot.count(UnitTypeId.DRONE)
            and 3 <= bot.townhalls.ready.amount
            and 4 <= bot.townhalls.amount
        ):
            if bot.count(UnitTypeId.HYDRALISKDEN) < 1:
                macroTargets.append(UnitTypeId.HYDRALISKDEN)
            # if bot.count(UnitTypeId.BANELINGNEST) < 1:
            #     macroTargets.append(UnitTypeId.BANELINGNEST)
            elif bot.count(UnitTypeId.EVOLUTIONCHAMBER) < 2:
                macroTargets.append(UnitTypeId.EVOLUTIONCHAMBER)
            elif bot.count(UnitTypeId.INFESTATIONPIT) < 1:
                macroTargets.append(UnitTypeId.INFESTATIONPIT)
            elif bot.count(UnitTypeId.HIVE) < 1:
                macroTargets.append(UnitTypeId.HIVE)
            # if bot.count(UnitTypeId.SPIRE) + bot.count(UnitTypeId.GREATERSPIRE) < 1:
            #     macroTargets.append(UnitTypeId.SPIRE)
            # if bot.count(UnitTypeId.GREATERSPIRE) == 0: 
            #     macroTargets.append(UnitTypeId.GREATERSPIRE)


        if bot.count(UnitTypeId.OVERLORD) < bot.getSupplyTarget():
            macroTargets.append(UnitTypeId.OVERLORD)

        unitTarget = []
        if .5 < armyRatio and bot.count(UnitTypeId.DRONE) < workers_target:
            unitTarget = [UnitTypeId.DRONE]
        else:
            if not bot.structures({ UnitTypeId.ROACHWARREN, UnitTypeId.HYDRALISKDEN }).ready.exists:
                unitTarget = [UnitTypeId.ZERGLING]
            elif bot.count(UnitTypeId.ROACH) < bot.count(UnitTypeId.HYDRALISK):
                unitTarget = [UnitTypeId.ROACH, UnitTypeId.HYDRALISK]
            else:
                unitTarget = [UnitTypeId.HYDRALISK, UnitTypeId.ROACH]
            # if not bot.structures(UnitTypeId.ROACHWARREN).ready.exists:
            #     unitTarget.append(UnitTypeId.ZERGLING)

        # if 1000 <= bot.minerals:
        #     unitTarget.append(UnitTypeId.ZERGLING)

        expandTarget = []
        if bot.already_pending(UnitTypeId.HATCHERY) < (2 if bot.supply_used < 30 else 1) and 0.5 < armyRatio:
            expandTarget.append(UnitTypeId.HATCHERY)

        return macroTargets + upgradeTargets + unitTarget + expandTarget