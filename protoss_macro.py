
import random

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.buff_id import BuffId

from bot_strategy import BotStrategy

class ProtossMacro(BotStrategy):

    def __init__(self):
        super(self.__class__, self).__init__()

    async def on_step(self, bot, iteration):
        await bot.chronoBoost(bot)
        bot.convertGateways(bot)

    def getTargets(self, bot):

        upgradeTargets = [

            UpgradeId.WARPGATERESEARCH,
            UpgradeId.CHARGE,

            UpgradeId.PROTOSSSHIELDSLEVEL1,
            UpgradeId.PROTOSSSHIELDSLEVEL2,
            UpgradeId.PROTOSSSHIELDSLEVEL3,

            # UpgradeId.PROTOSSGROUNDWEAPONSLEVEL1,
            # UpgradeId.PROTOSSGROUNDWEAPONSLEVEL2,
            # UpgradeId.PROTOSSGROUNDWEAPONSLEVEL3,
            # UpgradeId.PROTOSSGROUNDARMORSLEVEL1,
            # UpgradeId.PROTOSSGROUNDARMORSLEVEL2,
            # UpgradeId.PROTOSSGROUNDARMORSLEVEL3,

            UpgradeId.PROTOSSAIRWEAPONSLEVEL1,
            UpgradeId.PROTOSSAIRARMORSLEVEL1,
            UpgradeId.PROTOSSAIRWEAPONSLEVEL2,
            UpgradeId.PROTOSSAIRARMORSLEVEL2,
            UpgradeId.PROTOSSAIRWEAPONSLEVEL3,
            UpgradeId.PROTOSSAIRARMORSLEVEL3,
        ]

        workers_target = 1
        workers_target += sum([h.ideal_harvesters for h in bot.townhalls.ready])
        workers_target += 16 * (bot.townhalls.not_ready.amount + bot.already_pending(UnitTypeId.HATCHERY))
        workers_target += sum([e.ideal_harvesters for e in bot.gas_buildings.ready])
        workers_target += 3 * (bot.gas_buildings.not_ready.amount + bot.already_pending(UnitTypeId.EXTRACTOR))
        workers_target = max(30, workers_target)
        workers_target = min(66, workers_target)

        macroTargets = []

        if bot.count(UnitTypeId.PYLON) < bot.getSupplyTarget():
            macroTargets.append(UnitTypeId.PYLON)

        if bot.count(UnitTypeId.PROBE) < workers_target:
            macroTargets.append(UnitTypeId.PROBE)

        gateyways_target = 0
        if 16 <= bot.supply_used:
            gateyways_target += 1
        # if 2 <= bot.townhalls.amount:
        #     gateyways_target = min(12, int(bot.workers.amount / 8))

        if bot.count(UnitTypeId.GATEWAY) + bot.count(UnitTypeId.WARPGATE) < gateyways_target:
            macroTargets.append(UnitTypeId.GATEWAY)

        if 17 <= bot.supply_used:
            gas_target = bot.gas_buildings.filter(lambda g: not g.has_vespene).amount + min(8, 2 * bot.townhalls.ready.amount)
        else:
            gas_target = 0

        if bot.count(UnitTypeId.ASSIMILATOR) < gas_target:
            macroTargets.append(UnitTypeId.ASSIMILATOR)

        if bot.count(UnitTypeId.CYBERNETICSCORE) == 0:
            macroTargets.append(UnitTypeId.CYBERNETICSCORE)

        if bot.count(UnitTypeId.ROBOTICSFACILITY) < 1:
            macroTargets.append(UnitTypeId.ROBOTICSFACILITY)

        if bot.count(UnitTypeId.STARGATE) < min(4, int(bot.workers.amount / 20)):
            macroTargets.append(UnitTypeId.STARGATE)

        if 3 <= bot.townhalls.amount:
            if bot.count(UnitTypeId.TWILIGHTCOUNCIL) == 0:
                macroTargets.append(UnitTypeId.TWILIGHTCOUNCIL)
            # if bot.count(UnitTypeId.ROBOTICSBAY) == 0:
            #     macroTargets.append(UnitTypeId.ROBOTICSBAY)
            if bot.count(UnitTypeId.FLEETBEACON) == 0:
                macroTargets.append(UnitTypeId.FLEETBEACON)

        if bot.count(UnitTypeId.FORGE) < max(0, min(1, bot.townhalls.amount - 2)):
            macroTargets.append(UnitTypeId.FORGE)

        if bot.count(UnitTypeId.OBSERVER) < 1:
            macroTargets.append(UnitTypeId.OBSERVER)

        armyTargets = [UnitTypeId.ADEPT, UnitTypeId.STALKER, UnitTypeId.VOIDRAY, UnitTypeId.CARRIER, UnitTypeId.IMMORTAL, UnitTypeId.COLOSSUS]
        random.shuffle(armyTargets)

        expandTarget = []
        if bot.already_pending(UnitTypeId.NEXUS) == 0:
            expandTarget.append(UnitTypeId.NEXUS)

        return upgradeTargets + armyTargets + macroTargets + expandTarget

    async def chronoBoost(self, bot):
        if bot.supply_used < 16:
            return
        targets = bot.structures({ UnitTypeId.CYBERNETICSCORE, UnitTypeId.FORGE, UnitTypeId.ROBOTICSBAY, UnitTypeId.NEXUS })
        targets = targets.ready
        targets = targets.filter(lambda t: not t.is_idle)
        targets = targets.filter(lambda t: BuffId.CHRONOBOOSTENERGYCOST not in t.buffs)
        townhall = self.townhalls.random
        ability = AbilityId.EFFECT_CHRONOBOOSTENERGYCOST
        abilities = await bot.get_available_abilities(townhall)
        if ability in abilities and targets.exists:
            target = list(targets)[0]
            townhall(ability, target)

    def convertGateways(self, bot):
        if not UpgradeId.WARPGATERESEARCH in self.state.upgrades:
            return
        gateways = bot.structures(UnitTypeId.GATEWAY).ready.idle
        if gateways.exists:
            gateway = gateways.random
            gateway(AbilityId.MORPH_GATEWAY)