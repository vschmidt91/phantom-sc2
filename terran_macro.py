

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2

from bot_strategy import BotStrategy

class TerranMacro(BotStrategy):

    def __init__(self):
        super(self.__class__, self).__init__()

    async def on_step(self, bot, iteration):
        await self.dropMules(bot)
        await self.landFlyingBuildings(bot)
        self.buildAbandonedBuildings(bot)
        await super(self.__class__, self).on_step(bot, iteration)

    def getChain(self, bot):
        return [
            lambda reserve : self.buildAddons(bot, reserve),
            lambda reserve : self.manageCCs(bot, reserve),
            bot.macro,
        ]

    async def on_building_construction_complete(self, bot, unit):
        if unit.type_id == UnitTypeId.SUPPLYDEPOT:
            unit(AbilityId.MORPH_SUPPLYDEPOT_LOWER)

    def getTargets(self, bot):

        upgradeTargets = [

            # UpgradeId.SHIELDWALL,
            # UpgradeId.STIMPACK,
            # UpgradeId.PUNISHERGRENADES,

            # UpgradeId.TERRANINFANTRYWEAPONSLEVEL1,
            # UpgradeId.TERRANINFANTRYARMORSLEVEL1,
            # UpgradeId.TERRANINFANTRYWEAPONSLEVEL2,
            # UpgradeId.TERRANINFANTRYARMORSLEVEL2,
            # UpgradeId.TERRANINFANTRYWEAPONSLEVEL3,
            # UpgradeId.TERRANINFANTRYARMORSLEVEL3,

            UpgradeId.TERRANVEHICLEWEAPONSLEVEL1,
            UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL1,
            UpgradeId.TERRANVEHICLEWEAPONSLEVEL2,
            UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL2,
            UpgradeId.TERRANVEHICLEWEAPONSLEVEL3,
            UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL3,

            UpgradeId.TERRANSHIPWEAPONSLEVEL1,
            UpgradeId.TERRANSHIPWEAPONSLEVEL2,
            UpgradeId.TERRANSHIPWEAPONSLEVEL3,

        ]

        workers_target = 1
        workers_target += sum([h.ideal_harvesters for h in bot.townhalls.ready])
        workers_target += 16 * (bot.townhalls.not_ready.amount + bot.already_pending(UnitTypeId.HATCHERY))
        workers_target += sum([e.ideal_harvesters for e in bot.gas_buildings.ready])
        workers_target += 3 * (bot.gas_buildings.not_ready.amount + bot.already_pending(UnitTypeId.EXTRACTOR))
        
        workers_target = max(30, workers_target)
        workers_target = min(72, workers_target)

        macroTargets = []

        if bot.count(UnitTypeId.SUPPLYDEPOT) < bot.getSupplyTarget():
            macroTargets.append(UnitTypeId.SUPPLYDEPOT)

        if bot.count(UnitTypeId.ORBITALCOMMAND) < 3:
            macroTargets.append(UnitTypeId.ORBITALCOMMAND)
        else:
            macroTargets.append(UnitTypeId.PLANETARYFORTRESS)

        if bot.count(UnitTypeId.SCV) < workers_target:
            macroTargets.append(UnitTypeId.SCV)
        
        if 18 <= bot.supply_used:
            gas_target = bot.gas_buildings.filter(lambda g: not g.has_vespene).amount + min(8, 2 * bot.townhalls.ready.amount)
        else:
            gas_target = 0

        if bot.count(UnitTypeId.REFINERY) < gas_target:
            macroTargets.append(UnitTypeId.REFINERY)

        # if bot.count(UnitTypeId.BARRACKS) < min(12, int(sebotlf.workers.amount / 7)):
        if bot.count(UnitTypeId.BARRACKS) < 1:
            macroTargets.append(UnitTypeId.BARRACKS)

        if bot.count(UnitTypeId.FACTORY) < 1 + bot.townhalls.amount:
            macroTargets.append(UnitTypeId.FACTORY)

        if bot.count(UnitTypeId.STARPORT) < min(2, int(bot.workers.amount / 22)):
            macroTargets.append(UnitTypeId.STARPORT)

        if bot.count(UnitTypeId.ARMORY) < max(0, min(2, bot.townhalls.amount - 1)):
            macroTargets.append(UnitTypeId.ARMORY)

        # if 3 <= bot.townhalls.amount:
            # if bot.count(UnitTypeId.ARMORY) == 0:
            #     macroTargets.append(UnitTypeId.ARMORY)
        if 4 <= bot.townhalls.amount:
            if bot.count(UnitTypeId.FUSIONCORE) == 0:
                macroTargets.append(UnitTypeId.FUSIONCORE)

        armyTargets = [UnitTypeId.THOR, UnitTypeId.BATTLECRUISER, UnitTypeId.HELLION]

        if bot.count(UnitTypeId.RAVEN) < 1:
            armyTargets.append(UnitTypeId.RAVEN)

        # if self.count(UnitTypeId.MEDIVAC) < 4:
        #     armyTargets.append(UnitTypeId.MEDIVAC)

        # if self.count(UnitTypeId.MARINE) < 2 * self.count(UnitTypeId.MARAUDER):
        #     armyTargets += [UnitTypeId.MARINE, UnitTypeId.MARAUDER]
        # else:
        #     armyTargets += [UnitTypeId.MARAUDER, UnitTypeId.MARINE]
        
        expandTarget = []
        if bot.already_pending(UnitTypeId.COMMANDCENTER) == 0:
            expandTarget.append(UnitTypeId.COMMANDCENTER)

        return upgradeTargets + armyTargets + macroTargets + expandTarget

    async def manageCCs(self, bot, reserve):

        gases = self.gas_buildings.filter(lambda g: g.has_vespene)
        minedOutCCs = self.townhalls.ready.idle
        minedOutCCs = self.structures({ UnitTypeId.COMMANDCENTER, UnitTypeId.ORBITALCOMMAND })
        minedOutCCs = minedOutCCs.filter(lambda cc: not self.mineral_field.closer_than(10, cc).exists)
        # minedOutCCs = minedOutCCs.filter(lambda cc: not gases.closer_than(10, cc).exists)
        if minedOutCCs.exists:
            cc = minedOutCCs.random
            cc(AbilityId.LIFT)

        # townhalls = self.townhalls.ready.idle
        # if townhalls.exists:
        #     townhall = townhalls.random
        #     buildOrbitals = self.townhalls.amount <= 3
        #     if townhall.type_id == UnitTypeId.COMMANDCENTER and buildOrbitals and self.tech_requirement_progress(UnitTypeId.ORBITALCOMMAND) == 1:
        #         if self.canAffordWithReserve(UnitTypeId.ORBITALCOMMAND, reserve) and townhall.build(UnitTypeId.ORBITALCOMMAND):
        #             return reserve
        #         else:
        #             return reserve + self.createReserve(UnitTypeId.ORBITALCOMMAND)
        #     elif townhall.type_id == UnitTypeId.COMMANDCENTER and not buildOrbitals and self.tech_requirement_progress(UnitTypeId.PLANETARYFORTRESS) == 1:
        #         if self.canAffordWithReserve(UnitTypeId.PLANETARYFORTRESS, reserve) and townhall.build(UnitTypeId.PLANETARYFORTRESS):
        #             return reserve
        #         else:
        #             return reserve + self.createReserve(UnitTypeId.PLANETARYFORTRESS)

        return reserve

    async def dropMules(self, bot):

        orbitals = self.townhalls.of_type(UnitTypeId.ORBITALCOMMAND)
        if orbitals.exists and bot.mineral_field.exists:
            orbital = orbitals.random
            ability = AbilityId.CALLDOWNMULE_CALLDOWNMULE
            abilities = await bot.get_available_abilities(orbital)
            if ability in abilities:
                mineral = bot.mineral_field.closest_to(orbital)
                orbital(ability, mineral)

    async def buildAddonSingle(self, bot, reserve, structure, addon, reserveIfCannotAfford=False):
        if not bot.canAffordWithReserve(addon, reserve):
            if reserveIfCannotAfford:
                reserve = reserve + bot.createReserve(addon)
        elif not await bot.canPlaceAddon(structure.position):
            structure(AbilityId.LIFT)
        else:
            assert(structure.build(addon))
        return reserve

    async def buildAddons(self, bot, reserve, reserveIfCannotAfford=False):
        
        structures = bot.structures({ UnitTypeId.BARRACKS, UnitTypeId.STARPORT, UnitTypeId.FACTORY })
        structures = structures.ready.idle
        if structures.exists:
            structure = structures.random
            if not structure.has_add_on:
                if structure.type_id == UnitTypeId.BARRACKS:
                    addon = None
                    # addon = random.choice((UnitTypeId.BARRACKSREACTOR, UnitTypeId.BARRACKSTECHLAB))
                elif structure.type_id == UnitTypeId.FACTORY:
                    if 1.5 * bot.count(UnitTypeId.FACTORYTECHLAB) < bot.count(UnitTypeId.FACTORYREACTOR):
                        addon = UnitTypeId.FACTORYTECHLAB
                    else:
                        addon = UnitTypeId.FACTORYREACTOR
                    # addon = random.choice((UnitTypeId.FACTORYREACTOR, UnitTypeId.FACTORYTECHLAB))
                elif structure.type_id == UnitTypeId.STARPORT:
                    addon = UnitTypeId.STARPORTTECHLAB
                else:
                    addon = None
                if addon is not None:
                    reserve = await self.buildAddonSingle(reserve, bot, structure, addon, reserveIfCannotAfford=reserveIfCannotAfford)

        return reserve

    def buildAbandonedBuildings(self, bot):

        if bot.structures_without_construction_SCVs.exists:
            structure = bot.structures_without_construction_SCVs.random
            worker = bot.select_build_worker(structure.position)
            if worker is not None:
                worker(AbilityId.SMART, structure)
                    
    async def landFlyingBuildings(self, bot):

        offsets = sorted(
            (Point2((x, y)) for x in range(-10, 10) for y in range(-10, 10)),
            key=lambda point: point.x ** 2 + point.y ** 2,
        )
        halfOffset: Point2 = Point2((-0.5, -0.5))

        flyingProductionBuildings = bot.structures({ UnitTypeId.BARRACKSFLYING, UnitTypeId.FACTORYFLYING, UnitTypeId.STARPORTFLYING })
        flyingProductionBuildings = flyingProductionBuildings.ready.idle
        if flyingProductionBuildings.exists:
            building = flyingProductionBuildings.random
            possible_land_positions = (building.position.rounded + halfOffset + p for p in offsets)
            for p in possible_land_positions:
                if await bot.canPlace(p, building.type_id) and await bot.canPlaceAddon(p):
                    building(AbilityId.LAND, p)
                    break

        flyingCCs = bot.structures({ UnitTypeId.COMMANDCENTERFLYING, UnitTypeId.ORBITALCOMMANDFLYING })
        flyingCCs = flyingCCs.ready.idle
        if flyingCCs.exists:
            cc = flyingCCs.random
            expansion = await bot.get_next_expansion()
            if expansion is not None:
                if not cc(AbilityId.LAND, expansion):
                    cc.move(expansion)