
import math
import random
from utils import CHANGELINGS, armyValue, center, doChain, filterArmy, hasCapacity

import numpy as np
from sc2.position import Point2

import inspect

from sc2 import Race, BotAI
from sc2.constants import ALL_GAS
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.ids.upgrade_id import UpgradeId
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.constants import EQUIVALENTS_FOR_TECH_PROGRESS
from sc2.constants import IS_STRUCTURE
from sc2.data import Alliance, Result, race_townhalls, race_worker
from sc2.dicts.unit_research_abilities import RESEARCH_INFO
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.dicts.unit_tech_alias import UNIT_TECH_ALIAS
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2

from zerg_12pool import Zerg12Pool
from zerg_macro import ZergMacro
from protoss_macro import ProtossMacro
from terran_macro import TerranMacro

from bot_strategy import BotStrategy
from reserve import Reserve

SUPPLY = {
    Race.Protoss: UnitTypeId.PYLON,
    Race.Terran: UnitTypeId.SUPPLYDEPOT,
    Race.Zerg: UnitTypeId.OVERLORD,
}

TOWNHALL = {
    Race.Protoss: UnitTypeId.NEXUS,
    Race.Terran: UnitTypeId.COMMANDCENTER,
    Race.Zerg: UnitTypeId.HATCHERY,
}

class iBot(BotAI):

    strategy: BotStrategy

    def __init__(self, rush: bool):
        self.raw_affects_selection = True
        self.rush = rush

    async def on_before_start(self):
        if self.race == Race.Zerg:
            if self.rush:
                self.strategy = Zerg12Pool()
            else:
                self.strategy = ZergMacro()
        await self.strategy.on_before_start(self)

    async def on_building_construction_complete(self, unit: Unit):
        if unit.type_id in race_townhalls[self.race] and self.mineral_field.exists:
            mf = self.mineral_field.closest_to(unit)
            unit.smart(mf)
        pass

    async def on_building_construction_started(self, unit: Unit):
        await self.strategy.on_building_construction_started(self, unit)

    async def on_end(self, game_result: Result):
        await self.strategy.on_end(self, game_result)

    async def on_enemy_unit_entered_vision(self, unit: Unit):
        await self.strategy.on_enemy_unit_entered_vision(self, unit)

    async def on_enemy_unit_left_vision(self, unit_tag: int):
        await self.strategy.on_enemy_unit_left_vision(self, unit_tag)

    async def on_start(self):
        await self.strategy.on_start(self)

    async def on_step(self, iteration: int):

        if 2 <= self.townhalls.ready.amount:
            if type(self.strategy) is not ZergMacro:
                self.strategy = ZergMacro()

        await self.strategy.on_step(self, iteration)

        if not self.townhalls.exists:
            # await self.client.debug_leave()
            return

        self.assignWorker(harvestGas=self.strategy.harvestGas)
        self.micro(destroyRocks=self.strategy.destroyRocks)
        chain = self.strategy.getChain(self)
        reserve = await doChain(chain)

        # if 0 < len(reserve.items):
        #     print(reserve)

        pass

    async def on_unit_created(self, unit: Unit):
        await self.strategy.on_unit_created(self, unit)

    async def on_unit_destroyed(self, unit_tag: int):
        await self.strategy.on_unit_destroyed(self, unit_tag)

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float):
        if unit.type_id == UnitTypeId.OVERLORD:
            enemies = self.enemy_units | self.enemy_structures
            if enemies.exists:
                enemy = enemies.closest_to(unit)
                unit.move(unit.position.towards(enemy.position, -20))
            else:
                unit.move(unit.position.towards(self.start_location, 20))
        if (
            unit.is_structure
            and not unit.is_ready
            and unit.health_percentage < 0.333 * unit.build_progress * unit.build_progress
        ):
            unit(AbilityId.CANCEL)
            self.strategy.on_unit_took_damage(self, unit, amount_damage_taken)
        await self.strategy.on_unit_took_damage(self, unit, amount_damage_taken)

    async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId):
        await self.strategy.on_unit_type_changed(self, unit, previous_type)

    async def on_upgrade_complete(self, upgrade: UpgradeId):
        await self.strategy.on_upgrade_complete(self, upgrade)

    async def microQueens(self):

        tumors = self.structures(UnitTypeId.CREEPTUMORBURROWED).ready
        if tumors.exists:
            for _ in range(min(tumors.amount, 5)):
                tumor = tumors.random
                if AbilityId.BUILD_CREEPTUMOR_TUMOR in await self.get_available_abilities(tumor):
                    await self.buildCreepTumor(tumor)

        queens = self.units(UnitTypeId.QUEEN)
        hatcheries = sorted(self.townhalls, key=lambda h: h.tag)
        queens = sorted(queens, key=lambda q: q.tag)

        for hatchery, queen in zip(hatcheries, queens):
            if not queen.is_idle:
                return
            abilities = await self.get_available_abilities(queen)
            if (
                AbilityId.BUILD_CREEPTUMOR_QUEEN in abilities
                and 5 < self.larva.amount
                and random.random() < max(.1, math.exp(-.1 * self.count(UnitTypeId.CREEPTUMORBURROWED)))
            ):
                await self.buildCreepTumor(queen)
            elif AbilityId.EFFECT_INJECTLARVA in abilities and hatchery.is_ready:
                    queen(AbilityId.EFFECT_INJECTLARVA, hatchery)
            elif 5 < queen.distance_to(hatchery):
                queen.attack(hatchery.position)

    def micro(self, destroyRocks=True):

        army = filterArmy(self.units) | self.units({
            UnitTypeId.RAVEN,
            UnitTypeId.BROODLORD,
            UnitTypeId.OVERSEER,
            UnitTypeId.BANELING,
            UnitTypeId.MEDIVAC,
            UnitTypeId.BATTLECRUISER,
            UnitTypeId.VOIDRAY,
            UnitTypeId.CARRIER,
            UnitTypeId.OBSERVER })

        enemyArmy = self.enemy_units

        armyRatio = (1 + armyValue(filterArmy(army))) / (1 + armyValue(filterArmy(enemyArmy)))

        # if army.amount < 4 and armyRatio < 0.2 and enemyArmy.closer_than(20, self.start_location).exists:
        #     army = army | self.units(UnitTypeId.QUEEN)

        if not enemyArmy.exists:
            enemyArmy = self.enemy_units | self.enemy_structures

        # if destroyRocks:
        #     print("destroyRocks")

        neutrals = {}

        rocks = self.all_units.structure.filter(lambda r: "Destructible" in r.name)
        rocks = rocks.filter(lambda r: r.distance_to(self.start_location) < 2 * r.distance_to(self.enemy_start_locations[0]))

        neutrals = self.enemy_units(CHANGELINGS)

        # if army.exists:
        #     unit = army.random

        for unit in army:

            enemies = enemyArmy.closer_than(16, unit)

            friends = army.closer_than(16, unit)

            if enemyArmy.exists:
                target = enemyArmy.closest_to(self.start_location).position
            elif neutrals.exists:
                target = neutrals.closest_to(unit)
            elif rocks.exists and destroyRocks:
                target = rocks.closest_to(unit)
            else:
                target = random.choice(self.enemy_start_locations)

            if target is Unit:
                enemyValue = sum([(e.shield + e.health) * e.calculate_dps_vs_target(unit) for e in enemies])
                friendsValue = sum([(f.shield + f.health) * f.calculate_dps_vs_target(target) for f in friends])
            else:
                enemyValue = sum([(e.shield + e.health) * max(e.ground_dps, e.air_dps) for e in enemies])
                friendsValue = sum([(f.shield + f.health) * max(f.ground_dps, f.air_dps) for f in friends])

            defendersBias = 32
            defendersAdvantage = (defendersBias + unit.distance_to(self.enemy_start_locations[0])) / (defendersBias + unit.distance_to(self.start_location))
            defendersAdvantage = max(1, defendersAdvantage)

            if defendersAdvantage * friendsValue < enemyValue:
                retreatTo = unit.position.towards(center(enemies), -16)
                unit.move(retreatTo)
            else:
                unit.attack(target)

    async def changelingScout(self):

        overseers = self.units({
            UnitTypeId.OVERSEER,
            UnitTypeId.OVERSEERSIEGEMODE
        })
        if overseers.exists:
            overseer = overseers.random
            ability = TRAIN_INFO[overseer.type_id][UnitTypeId.CHANGELING]["ability"]
            if ability in await self.get_available_abilities(overseer):
                overseer(ability)

        changelings = self.units(CHANGELINGS).idle
        if changelings.exists:
            changeling = changelings.random
            target = self.getScoutTarget()
            changeling.move(target)

    def getScoutTarget(self):
        enemies = self.enemy_structures | self.enemy_units
        # if enemies.exists:
        #     return random.choice(enemies).position
        # else:
        return random.choice(self.expansion_locations_list)

    def moveOverlord(self, bias=1):
        overlords = self.units(UnitTypeId.OVERLORD).idle
        if overlords.exists:
            overlord = overlords.random
            bases = [
                p for p in self.expansion_locations_list
                if (lambda p: p.distance_to(self.start_location) < p.distance_to(self.enemy_start_locations[0]))
            ]
            p = [
                (bias + b.distance_to(self.enemy_start_locations[0])) / (bias + b.distance_to(self.start_location))
                for b in bases
            ]
            ps = sum(p)
            p = [pi / ps for pi in p]
            bi = np.random.choice(range(len(bases)), p=p)
            target = bases[bi]
            # target = self.getScoutTarget()
            overlord.move(target)

    def isStructure(self, unit):
        if unit.value not in self.game_data.units:
            return False
        unitData = self.game_data.units[unit.value]
        return IS_STRUCTURE in unitData.attributes

    def getSupplyBuffer(self):
        supplyBuffer = 0
        supplyBuffer += self.townhalls.amount
        supplyBuffer += 3 * self.units(UnitTypeId.QUEEN).amount
        supplyBuffer += 2 * self.structures(UnitTypeId.BARRACKS).amount
        supplyBuffer += 2 * self.structures(UnitTypeId.FACTORY).amount
        supplyBuffer += 2 * self.structures(UnitTypeId.STARPORT).amount
        supplyBuffer += 2 * self.structures(UnitTypeId.GATEWAY).amount
        supplyBuffer += 2 * self.structures(UnitTypeId.WARPGATE).amount
        supplyBuffer += 2 * self.structures(UnitTypeId.ROBOTICSFACILITY).amount
        supplyBuffer += 2 * self.structures(UnitTypeId.STARGATE).amount
        return supplyBuffer

    def getSupplyTarget(self):

        unit = SUPPLY[self.race]
        if self.isStructure(unit):
            supplyActual = self.structures(unit).amount
        else:
            supplyActual = self.units(unit).amount
        if self.supply_cap == 200:
            return supplyActual
        supplyPending = self.already_pending(unit)
        supplyBuffer = self.getSupplyBuffer()
        supplyNeeded = 1 + math.floor((supplyBuffer - self.supply_left) / 8) - supplyPending
        return supplyActual + supplyNeeded

    def count(self, unit):
        return self.structures(unit).amount + self.units(unit).amount + self.already_pending(unit)

    async def reachTarget(self, target, reserve):

        if self.tech_requirement_progress(target) < 1:
            return reserve

        if type(target) is UnitTypeId:
            trainerTypes = UNIT_TRAINED_FROM[target]
        elif type(target) is UpgradeId:
            if target in self.state.upgrades:
                return reserve
            elif self.already_pending_upgrade(target):
                return reserve
            trainerTypes = UPGRADE_RESEARCHED_FROM[target]
        else:
            return reserve

        trainers = self.structures(trainerTypes) | self.units(trainerTypes)
        trainers = trainers.ready
        for trainer in trainers:

            if trainer.tag in reserve.trainers:
                continue

            if not hasCapacity(trainer):
                continue

            if type(target) is UnitTypeId:
                info = TRAIN_INFO[trainer.type_id][target]
            elif type(target) is UpgradeId:
                info = RESEARCH_INFO[trainer.type_id][target]
            else:
                continue

            if "requires_techlab" in info and not trainer.has_techlab:
                continue

            ability = info["ability"]

            if "required_building" in info:
                building = info["required_building"]
                if building in EQUIVALENTS_FOR_TECH_PROGRESS:
                    building = { building } | EQUIVALENTS_FOR_TECH_PROGRESS[building]
                if not self.structures(building).ready.exists:
                    continue
            if "required_upgrade" in info:
                upgrade = info["required_upgrade"]
                if not upgrade in self.state.upgrades:
                    continue

            if not self.canAffordWithReserve(target, reserve):
                reserve = reserve + self.createReserve(target, trainer)
                break

            abilities = await self.get_available_abilities(trainer)
            if not ability in abilities:
                # print(abilities)
                continue

            if target in ALL_GAS:
                geysers = []
                for b in self.owned_expansions.keys():
                    geysers += [g for g in self.expansion_locations_dict[b] if g.has_vespene]
                geysers = Units(geysers, self)
                geysers = geysers.filter(lambda g : not self.gas_buildings.closer_than(1, g).exists)
                # geysers = geysers.filter(lambda g : not self.workers.filter(lambda w : w.order_target == g.tag).exists)
                if not geysers.exists:
                    continue
                abilityTarget = geysers.closest_to(trainer.position)
            elif "requires_placement_position" in info:
                maxDistance = 20
                if self.isStructure(target):
                    if target in race_townhalls[self.race]:
                        position = await self.get_next_expansion()
                        maxDistance = 2
                    else:
                        position = self.townhalls.random.position
                        position = position.towards(self.game_info.map_center, 4)
                else:
                    position = trainer.position
                if not position:
                    continue
                withAddon = target in { UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT }
                abilityTarget = await self.find_placement(ability, position, max_distance=maxDistance, placement_step=1, addon_place=withAddon)
            else:
                abilityTarget = None

            if trainer.is_carrying_resource:
                trainer.return_resource()
                queue = True
            else:
                queue = False

            if abilityTarget is None:
                assert(trainer(ability, queue=queue))
            else:
                assert(trainer(ability, target=abilityTarget, queue=queue))

            break

        return reserve

    def assignWorker(self, harvestGas=True):

        worker = None
        target = None

        if self.workers.idle.exists:
            worker = self.workers.idle.random
            if self.townhalls.ready.exists:
                townhall = self.townhalls.ready.random
            else:
                townhall = self.townhalls.random
            minerals = self.mineral_field.closest_to(townhall)
            target = minerals

        if worker is None:
            for gas in self.gas_buildings.ready:
                workers = self.workers.filter(lambda w : w.order_target == gas.tag)
                if workers.exists and (0 < gas.surplus_harvesters or not harvestGas):
                    worker = workers.furthest_to(gas)
                elif gas.surplus_harvesters < 0 and harvestGas:
                    target = gas

        if worker is None:
            for townhall in self.townhalls.ready:
                if 0 < townhall.surplus_harvesters or target is not None:
                    minerals = self.mineral_field.closer_than(10, townhall.position)
                    minerals = [m.tag for m in minerals]
                    workers = self.workers.filter(lambda w : w.order_target in minerals)
                    if workers.exists:
                        worker = workers.furthest_to(townhall)
                        break

        if worker is None:
            return False

        if target is None:
            for gas in self.gas_buildings.ready:
                if gas.surplus_harvesters < 0 and harvestGas:
                    target = gas
                    break

        if target is None:
            for townhall in self.townhalls.ready:
                if townhall.surplus_harvesters < 0:
                    minerals = self.mineral_field.closest_to(townhall)
                    target = minerals

        if target is None:
            return False

        if worker.is_carrying_resource:
            worker.return_resource()
            worker.gather(target, queue=True)
        else:
            worker.gather(target)

        return True

    async def macro(self, reserve):
        targets = self.strategy.getTargets(self)
        for target in targets:
            reserve = await self.reachTarget(target, reserve)
        return reserve

    def canAffordWithReserve(self, item, reserve):
        cost = self.createReserve(item)
        if (
            (cost.minerals == 0 or cost.minerals + reserve.minerals <= self.minerals)
            and (cost.vespene == 0 or cost.vespene + reserve.vespene <= self.vespene)
            and (cost.food == 0 or cost.food + reserve.food <= self.supply_left)
        ):
            return True
        else:
            return False

    def createReserve(self, item, trainer=None):
        cost = self.calculate_cost(item)
        if isinstance(item, UnitTypeId):
            food = int(self.calculate_supply_cost(item))
        else:
            food = 0
        return Reserve(cost.minerals, cost.vespene, food, [0 if trainer is None else trainer.tag], [item.name])

    def canPlace(self, position, unit):
        if unit in UNIT_TECH_ALIAS:
            unit = list(UNIT_TECH_ALIAS[unit])[0]
        trainer = list(UNIT_TRAINED_FROM[unit])[0]
        ability = TRAIN_INFO[trainer][unit]["ability"]
        abilityData = self.game_data.abilities[ability.value]
        return self.can_place_single(abilityData, position)

    def canPlaceAddon(self, position):
        addonPosition = position + Point2((2.5, -0.5))
        return self.canPlace(addonPosition, UnitTypeId.SUPPLYDEPOT)

    def isBlockingExpansion(self, position):
        return any((e.distance_to(position) < 3 for e in self.expansion_locations_list))

    async def buildCreepTumor(self, unit):
        position = None
        d = unit.distance_to(self.start_location)
        choices = [e for e in self.expansion_locations_list if d < e.distance_to(self.start_location)]
        if 0 == len(choices):
            return
        w = [1.0 / e.distance_to(unit) for e in choices]
        ws = sum(w)
        p = [wi / ws for wi in w]
        for _ in range(3):
            ei = np.random.choice(list(range(len(choices))), p=p)
            expansion = choices[ei]
            position = unit.position.towards(expansion, 10)
            position = await self.find_placement(AbilityId.ZERGBUILD_CREEPTUMOR, position, placement_step=1)
            if position is None:
                continue
            if self.isBlockingExpansion(position):
                continue
            break
        if position is not None:
            assert(unit.build(UnitTypeId.CREEPTUMOR, position))