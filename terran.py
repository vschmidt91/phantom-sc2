

from macro_objective import MacroObjective
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2

from common import CommonAI

class TerranAI(CommonAI):

    def __init__(self):
        super(self.__class__, self).__init__()

    async def on_step(self, iteration):
        await self.dropMules()
        await self.landFlyingBuildings()
        self.buildAbandonedBuildings()
        await super(self.__class__, self).on_step(iteration)
        self.manageCCs()

        targets = self.getTargets()
        self.macroObjectives += [MacroObjective(t) for t in targets]

    def getChain(self):
        return [
            self.buildAddons,
            self.manageCCs,
            self.macro,
        ]

    async def on_building_construction_complete(self, unit):
        if unit.type_id == UnitTypeId.SUPPLYDEPOT:
            unit(AbilityId.MORPH_SUPPLYDEPOT_LOWER)
        await super(self.__class__, self).on_building_construction_complete(unit)

    def getTargets(self):

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
        workers_target += sum([h.ideal_harvesters for h in self.townhalls.ready])
        workers_target += 16 * (self.townhalls.not_ready.amount + self.already_pending(UnitTypeId.HATCHERY))
        workers_target += sum([e.ideal_harvesters for e in self.gas_buildings.ready])
        workers_target += 3 * (self.gas_buildings.not_ready.amount + self.already_pending(UnitTypeId.EXTRACTOR))
        
        workers_target = max(30, workers_target)
        workers_target = min(72, workers_target)

        macroTargets = []

        if self.count(UnitTypeId.SUPPLYDEPOT) < self.getSupplyTarget():
            macroTargets.append(UnitTypeId.SUPPLYDEPOT)

        if self.count(UnitTypeId.ORBITALCOMMAND) < 3:
            macroTargets.append(UnitTypeId.ORBITALCOMMAND)
        # else:
        #     macroTargets.append(UnitTypeId.PLANETARYFORTRESS)

        if self.count(UnitTypeId.SCV) < workers_target:
            macroTargets.append(UnitTypeId.SCV)
        
        if 18 <= self.supply_used:
            gas_target = self.gas_buildings.filter(lambda g: not g.has_vespene).amount + min(8, 2 * self.townhalls.ready.amount)
        else:
            gas_target = 0

        if self.count(UnitTypeId.REFINERY) < gas_target:
            macroTargets.append(UnitTypeId.REFINERY)
        self.gasTarget = 3 * gas_target

        if self.count(UnitTypeId.BARRACKS) < min(12, int(self.workers.amount / 7)):
        # if self.count(UnitTypeId.BARRACKS) < 1:
            macroTargets.append(UnitTypeId.BARRACKS)

        # if self.count(UnitTypeId.FACTORY) < 1 + self.townhalls.amount:
        if self.count(UnitTypeId.FACTORY) < 1:
            macroTargets.append(UnitTypeId.FACTORY)

        # if self.count(UnitTypeId.STARPORT) < min(2, int(self.workers.amount / 22)):
        if self.count(UnitTypeId.STARPORT) < 1:
            macroTargets.append(UnitTypeId.STARPORT)

        if self.count(UnitTypeId.ARMORY) < max(0, min(2, self.townhalls.amount - 1)):
            macroTargets.append(UnitTypeId.ARMORY)

        # if 3 <= self.townhalls.amount:
            # if self.count(UnitTypeId.ARMORY) == 0:
            #     macroTargets.append(UnitTypeId.ARMORY)
        if 4 <= self.townhalls.amount:
            if self.count(UnitTypeId.FUSIONCORE) == 0:
                macroTargets.append(UnitTypeId.FUSIONCORE)

        # armyTargets = [UnitTypeId.THOR, UnitTypeId.BATTLECRUISER, UnitTypeId.HELLION]

        # if self.count(UnitTypeId.RAVEN) < 1:
        #     armyTargets.append(UnitTypeId.RAVEN)

        # if self.count(UnitTypeId.MEDIVAC) < 4:
        #     armyTargets.append(UnitTypeId.MEDIVAC)

        armyTargets = []
        if 30 < self.count(UnitTypeId.SCV):
            if self.count(UnitTypeId.MARINE) < 2 * self.count(UnitTypeId.MARAUDER):
                armyTargets += [UnitTypeId.MARINE, UnitTypeId.MARAUDER]
            else:
                armyTargets += [UnitTypeId.MARAUDER, UnitTypeId.MARINE]

        armyTargets = [a for a in armyTargets if not any((o.item == a for o in self.macroObjectives))]
        
        expandTarget = []
        if self.already_pending(UnitTypeId.COMMANDCENTER) == 0 and not any((o.item == UnitTypeId.COMMANDCENTER for o in self.macroObjectives)):
            expandTarget.append(UnitTypeId.COMMANDCENTER)

        return armyTargets + macroTargets + expandTarget
        # return upgradeTargets + armyTargets + macroTargets + expandTarget

    async def manageCCs(self):

        gases = self.gas_buildings.filter(lambda g: g.has_vespene)
        minedOutCCs = self.townhalls.ready.idle
        minedOutCCs = self.structures({ UnitTypeId.COMMANDCENTER, UnitTypeId.ORBITALCOMMAND })
        minedOutCCs = minedOutCCs.filter(lambda cc: not self.mineral_field.closer_than(10, cc).exists)
        # minedOutCCs = minedOutCCs.filter(lambda cc: not gases.closer_than(10, cc).exists)
        if minedOutCCs.exists:
            cc = minedOutCCs.random
            cc(AbilityId.LIFT)

    async def dropMules(self):

        orbitals = self.townhalls.of_type(UnitTypeId.ORBITALCOMMAND)
        if orbitals.exists and self.mineral_field.exists:
            orbital = orbitals.random
            ability = AbilityId.CALLDOWNMULE_CALLDOWNMULE
            abilities = await self.get_available_abilities(orbital)
            if ability in abilities:
                mineral = self.mineral_field.closest_to(orbital)
                orbital(ability, mineral)

    async def buildAddonSingle(self, reserve, structure, addon, reserveIfCannotAfford=False):
        if not self.canAffordWithReserve(addon, reserve):
            if reserveIfCannotAfford:
                reserve = reserve + self.createReserve(addon)
        elif not await self.canPlaceAddon(structure.position):
            structure(AbilityId.LIFT)
        else:
            assert(structure.build(addon))
        return reserve

    async def buildAddons(self, reserve, reserveIfCannotAfford=False):
        
        structures = self.structures({ UnitTypeId.BARRACKS, UnitTypeId.STARPORT, UnitTypeId.FACTORY })
        structures = structures.ready.idle
        if structures.exists:
            structure = structures.random
            if not structure.has_add_on:
                if structure.type_id == UnitTypeId.BARRACKS:
                    addon = None
                    # addon = random.choice((UnitTypeId.BARRACKSREACTOR, UnitTypeId.BARRACKSTECHLAB))
                elif structure.type_id == UnitTypeId.FACTORY:
                    if 1.5 * self.count(UnitTypeId.FACTORYTECHLAB) < self.count(UnitTypeId.FACTORYREACTOR):
                        addon = UnitTypeId.FACTORYTECHLAB
                    else:
                        addon = UnitTypeId.FACTORYREACTOR
                    # addon = random.choice((UnitTypeId.FACTORYREACTOR, UnitTypeId.FACTORYTECHLAB))
                elif structure.type_id == UnitTypeId.STARPORT:
                    addon = UnitTypeId.STARPORTTECHLAB
                else:
                    addon = None
                if addon is not None:
                    reserve = await self.buildAddonSingle(reserve, self, structure, addon, reserveIfCannotAfford=reserveIfCannotAfford)

        return reserve

    def buildAbandonedBuildings(self):

        if self.structures_without_construction_SCVs.exists:
            structure = self.structures_without_construction_SCVs.random
            worker = self.select_build_worker(structure.position)
            if worker is not None:
                worker(AbilityId.SMART, structure)
                    
    async def landFlyingBuildings(self):

        offsets = sorted(
            (Point2((x, y)) for x in range(-10, 10) for y in range(-10, 10)),
            key=lambda point: point.x ** 2 + point.y ** 2,
        )
        halfOffset: Point2 = Point2((-0.5, -0.5))

        flyingProductionBuildings = self.structures({ UnitTypeId.BARRACKSFLYING, UnitTypeId.FACTORYFLYING, UnitTypeId.STARPORTFLYING })
        flyingProductionBuildings = flyingProductionBuildings.ready.idle
        if flyingProductionBuildings.exists:
            building = flyingProductionBuildings.random
            possible_land_positions = (building.position.rounded + halfOffset + p for p in offsets)
            for p in possible_land_positions:
                if await self.canPlace(p, building.type_id) and await self.canPlaceAddon(p):
                    building(AbilityId.LAND, p)
                    break

        flyingCCs = self.structures({ UnitTypeId.COMMANDCENTERFLYING, UnitTypeId.ORBITALCOMMANDFLYING })
        flyingCCs = flyingCCs.ready.idle
        if flyingCCs.exists:
            cc = flyingCCs.random
            expansion = await self.get_next_expansion()
            if expansion is not None:
                if not cc(AbilityId.LAND, expansion):
                    cc.move(expansion)

    def canPlaceAddon(self, position):
        addonPosition = position + Point2((2.5, -0.5))
        return self.canPlace(addonPosition, UnitTypeId.SUPPLYDEPOT)