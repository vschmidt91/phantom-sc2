
import random

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.buff_id import BuffId

from common import CommonAI

class ProtossAI(CommonAI):

    def __init__(self):
        super(self.__class__, self).__init__()

    async def on_step(self, iteration):
        await self.chronoBoost()
        self.convertGateways()
        await super(self.__class__, self).on_step(iteration)

    def getTargets(self):

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
        workers_target += sum([h.ideal_harvesters for h in self.townhalls.ready])
        workers_target += 16 * (self.townhalls.not_ready.amount + self.already_pending(UnitTypeId.HATCHERY))
        workers_target += sum([e.ideal_harvesters for e in self.gas_buildings.ready])
        workers_target += 3 * (self.gas_buildings.not_ready.amount + self.already_pending(UnitTypeId.EXTRACTOR))
        workers_target = max(30, workers_target)
        workers_target = min(66, workers_target)

        macroTargets = []

        if self.count(UnitTypeId.PYLON) < self.getSupplyTarget():
            macroTargets.append(UnitTypeId.PYLON)

        if self.count(UnitTypeId.PROBE) < workers_target:
            macroTargets.append(UnitTypeId.PROBE)

        gateyways_target = 0
        if 16 <= self.supply_used:
            gateyways_target += 1
        # if 2 <= self.townhalls.amount:
        #     gateyways_target = min(12, int(self.workers.amount / 8))

        if self.count(UnitTypeId.GATEWAY) + self.count(UnitTypeId.WARPGATE) < gateyways_target:
            macroTargets.append(UnitTypeId.GATEWAY)

        if 17 <= self.supply_used:
            gas_target = self.gas_buildings.filter(lambda g: not g.has_vespene).amount + min(8, 2 * self.townhalls.ready.amount)
        else:
            gas_target = 0

        if self.count(UnitTypeId.ASSIMILATOR) < gas_target:
            macroTargets.append(UnitTypeId.ASSIMILATOR)

        if self.count(UnitTypeId.CYBERNETICSCORE) == 0:
            macroTargets.append(UnitTypeId.CYBERNETICSCORE)

        if self.count(UnitTypeId.ROBOTICSFACILITY) < 1:
            macroTargets.append(UnitTypeId.ROBOTICSFACILITY)

        if self.count(UnitTypeId.STARGATE) < min(4, int(self.workers.amount / 20)):
            macroTargets.append(UnitTypeId.STARGATE)

        if 3 <= self.townhalls.amount:
            if self.count(UnitTypeId.TWILIGHTCOUNCIL) == 0:
                macroTargets.append(UnitTypeId.TWILIGHTCOUNCIL)
            # if self.count(UnitTypeId.ROBOTICSBAY) == 0:
            #     macroTargets.append(UnitTypeId.ROBOTICSBAY)
            if self.count(UnitTypeId.FLEETBEACON) == 0:
                macroTargets.append(UnitTypeId.FLEETBEACON)

        if self.count(UnitTypeId.FORGE) < max(0, min(1, self.townhalls.amount - 2)):
            macroTargets.append(UnitTypeId.FORGE)

        if self.count(UnitTypeId.OBSERVER) < 1:
            macroTargets.append(UnitTypeId.OBSERVER)

        armyTargets = [UnitTypeId.ADEPT, UnitTypeId.STALKER, UnitTypeId.VOIDRAY, UnitTypeId.CARRIER, UnitTypeId.IMMORTAL, UnitTypeId.COLOSSUS]
        random.shuffle(armyTargets)

        expandTarget = []
        if self.already_pending(UnitTypeId.NEXUS) == 0:
            expandTarget.append(UnitTypeId.NEXUS)

        return upgradeTargets + armyTargets + macroTargets + expandTarget

    async def chronoBoost(self):
        if self.supply_used < 16:
            return
        targets = self.structures({ UnitTypeId.CYBERNETICSCORE, UnitTypeId.FORGE, UnitTypeId.ROBOTICSBAY, UnitTypeId.NEXUS })
        targets = targets.ready
        targets = targets.filter(lambda t: not t.is_idle)
        targets = targets.filter(lambda t: BuffId.CHRONOBOOSTENERGYCOST not in t.buffs)
        townhall = self.townhalls.random
        ability = AbilityId.EFFECT_CHRONOBOOSTENERGYCOST
        abilities = await self.get_available_abilities(townhall)
        if ability in abilities and targets.exists:
            target = list(targets)[0]
            townhall(ability, target)

    def convertGateways(self):
        if not UpgradeId.WARPGATERESEARCH in self.state.upgrades:
            return
        gateways = self.structures(UnitTypeId.GATEWAY).ready.idle
        if gateways.exists:
            gateway = gateways.random
            gateway(AbilityId.MORPH_GATEWAY)