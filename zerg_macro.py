

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from bot_strategy import BotStrategy
from utils import armyValue, filterArmy

class ZergMacro(BotStrategy):

    def __init__(self):
        super(self.__class__, self).__init__()
        
    async def on_step(self, bot, iteration):
        await bot.microQueens()
        bot.moveOverlord()
        self.harvestGas = not bot.already_pending(UpgradeId.ZERGLINGMOVEMENTSPEED) or (UpgradeId.ZERGLINGMOVEMENTSPEED in bot.state.upgrades and 3 <= bot.townhalls.amount)
        await bot.changelingScout()

    def getTargets(self, bot):

        armyRatio = (1 + armyValue(filterArmy(bot.units))) / (1 + armyValue(filterArmy(bot.enemy_units)))

        upgradeTargets = []
        
        if 22 <= bot.supply_used:
            
            upgradeTargets += [
                UpgradeId.ZERGLINGMOVEMENTSPEED,
                UpgradeId.GLIALRECONSTITUTION,
                UpgradeId.CENTRIFICALHOOKS,
                UpgradeId.EVOLVEGROOVEDSPINES]

            if .5 < armyRatio:
                upgradeTargets += [
                    UpgradeId.EVOLVEMUSCULARAUGMENTS,
                    # UpgradeId.ZERGLINGATTACKSPEED,

                    # UpgradeId.ZERGMELEEWEAPONSLEVEL1,
                    # UpgradeId.ZERGMELEEWEAPONSLEVEL2,
                    # UpgradeId.ZERGMELEEWEAPONSLEVEL3,

                    UpgradeId.ZERGMISSILEWEAPONSLEVEL1,
                    UpgradeId.ZERGMISSILEWEAPONSLEVEL2,
                    UpgradeId.ZERGMISSILEWEAPONSLEVEL3,

                    UpgradeId.ZERGGROUNDARMORSLEVEL1,
                    UpgradeId.ZERGGROUNDARMORSLEVEL2,
                    UpgradeId.ZERGGROUNDARMORSLEVEL3,

                    # UpgradeId.ZERGFLYERWEAPONSLEVEL1,
                    # UpgradeId.ZERGFLYERARMORSLEVEL1,
                    # UpgradeId.ZERGFLYERWEAPONSLEVEL2,
                    # UpgradeId.ZERGFLYERARMORSLEVEL2,
                    # UpgradeId.ZERGFLYERWEAPONSLEVEL3,
                    # UpgradeId.ZERGFLYERARMORSLEVEL3,
                ]

        if 3 <= bot.townhalls.ready.amount:
            upgradeTargets.append(UpgradeId.OVERLORDSPEED)

        macroTargets = []
        
        if 17 <= bot.supply_used and bot.count(UnitTypeId.SPAWNINGPOOL) == 0:
            macroTargets.append(UnitTypeId.SPAWNINGPOOL)

        if 33 <= bot.count(UnitTypeId.DRONE) and 3 <= bot.townhalls.amount:
            if bot.count(UnitTypeId.ROACHWARREN) == 0:
                macroTargets.append(UnitTypeId.ROACHWARREN)
            if bot.count(UnitTypeId.EVOLUTIONCHAMBER) == 0:
                macroTargets.append(UnitTypeId.EVOLUTIONCHAMBER)
            if bot.count(UnitTypeId.LAIR) + bot.count(UnitTypeId.HIVE) == 0:
                macroTargets.append(UnitTypeId.LAIR)
            

        if 66 <= bot.count(UnitTypeId.DRONE) and 4 <= bot.townhalls.amount:
            if bot.count(UnitTypeId.HYDRALISKDEN) == 0:
                macroTargets.append(UnitTypeId.HYDRALISKDEN)
            if bot.count(UnitTypeId.INFESTATIONPIT) == 0:
                macroTargets.append(UnitTypeId.INFESTATIONPIT)
            # if bot.count(UnitTypeId.BANELINGNEST) == 0:
            #     macroTargets.append(UnitTypeId.BANELINGNEST)
            if bot.count(UnitTypeId.EVOLUTIONCHAMBER) < 2:
                macroTargets.append(UnitTypeId.EVOLUTIONCHAMBER)
            if bot.count(UnitTypeId.HIVE) == 0:
                macroTargets.append(UnitTypeId.HIVE)
            # if bot.count(UnitTypeId.SPIRE) + bot.count(UnitTypeId.GREATERSPIRE) < 1:
            #     macroTargets.append(UnitTypeId.SPIRE)
            # if bot.count(UnitTypeId.GREATERSPIRE) == 0:
            #     macroTargets.append(UnitTypeId.GREATERSPIRE)

        workers_target = 1
        workers_target += sum([h.ideal_harvesters for h in bot.townhalls.ready])
        workers_target += 16 * (bot.townhalls.not_ready.amount + bot.already_pending(UnitTypeId.HATCHERY))
        workers_target += sum([e.ideal_harvesters for e in bot.gas_buildings.ready])
        workers_target += 3 * (bot.gas_buildings.not_ready.amount + bot.already_pending(UnitTypeId.EXTRACTOR))
        workers_target = min(66, workers_target)

        if bot.count(UnitTypeId.OVERLORD) < bot.getSupplyTarget():
            macroTargets.append(UnitTypeId.OVERLORD)

        if bot.supply_used < 17 or not self.harvestGas:
            gas_target = 0
        # elif 2 == bot.townhalls.amount:
        #     gas_target = 1
        # elif 3 == bot.townhalls.amount:
        #     gas_target = 3
        else:
            gas_target = bot.gas_buildings.filter(lambda g: not g.has_vespene).amount + min(8, 2 * bot.townhalls.amount - 3)

        if bot.already_pending(UnitTypeId.EXTRACTOR) < 1 and bot.count(UnitTypeId.EXTRACTOR) < gas_target:
            macroTargets.append(UnitTypeId.EXTRACTOR)

        if bot.count(UnitTypeId.QUEEN) < min(5, bot.townhalls.amount):
            macroTargets.append(UnitTypeId.QUEEN)

        if bot.count(UnitTypeId.OVERSEER) == 0:
            macroTargets.append(UnitTypeId.OVERSEER)

        unitTarget = []
        if .5 < armyRatio and bot.count(UnitTypeId.DRONE) < workers_target:
            unitTarget = [UnitTypeId.DRONE]
        else:
            if bot.count(UnitTypeId.ROACH) < bot.count(UnitTypeId.HYDRALISK):
                unitTarget = [UnitTypeId.ROACH, UnitTypeId.HYDRALISK]
            else:
                unitTarget = [UnitTypeId.HYDRALISK, UnitTypeId.ROACH]
            if not bot.count(UnitTypeId.ROACHWARREN):
                unitTarget.append(UnitTypeId.ZERGLING)

        expandTarget = []
        if bot.already_pending(UnitTypeId.HATCHERY) < 1 and 0.5 < armyRatio:
            expandTarget.append(UnitTypeId.HATCHERY)

        return upgradeTargets + macroTargets + unitTarget + expandTarget