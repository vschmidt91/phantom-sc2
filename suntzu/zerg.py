
from collections import defaultdict
import inspect
import math
import itertools, random
import build
from typing import Counter, Iterable, List, Coroutine, Dict, Set, Union, Tuple
from itertools import chain

from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit
from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO

from .timer import run_timed
from .constants import CHANGELINGS, SUPPLY_PROVIDED
from .common import CommonAI
from .utils import sample
from .unit_counters import UNIT_COUNTERS
from .build_orders import ROACH_RUSH, HATCH17
from .constants import WITH_TECH_EQUIVALENTS, REQUIREMENTS, ZERG_ARMOR_UPGRADES, ZERG_MELEE_UPGRADES, ZERG_RANGED_UPGRADES, ZERG_FLYER_UPGRADES, ZERG_FLYER_ARMOR_UPGRADES
from .cost import Cost
from .macro_target import MacroTarget

CREEP_RANGE = 10
CREEP_ENABLED = True

SPORE_TIMING = {
    Race.Zerg: 7 * 60,
    Race.Protoss: 4.5 * 60,
    Race.Terran: 4.5 * 60,
}

class ZergAI(CommonAI):

    def __init__(self, build_order=ROACH_RUSH, **kwargs):
        super(self.__class__, self).__init__(**kwargs)

        if random.random() < 0.5:
            build_order = ROACH_RUSH
            self.tag = "RoachRush"
            self.tech_time = 4.25 * 60
            self.extractor_trick_enabled = False
            self.destroy_destructables = False
        else:
            build_order = HATCH17
            self.tag = "HatchFirst"
            self.tech_time = 3.5 * 60
            self.extractor_trick_enabled = False
            self.destroy_destructables = True

        for step in build_order:
            self.add_macro_target(MacroTarget(step, priority=10))

        self.composition = dict()
        self.timings_acc = dict()
        self.abilities = dict()
        self.inject_assigments = dict()
        self.timings_interval = 64
        self.inject_assigments_max = 5

    async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId):
        if unit.type_id == UnitTypeId.LAIR:
            ability = AbilityId.BEHAVIOR_GENERATECREEPON
            for overlord in self.units_by_type[UnitTypeId.OVERLORD]:
                if ability in await self.get_available_abilities(overlord):
                    overlord(ability)
                    
        # elif unit.type_id == UnitTypeId.EGG:
        #     unit_morph = UNIT_BY_TRAIN_ABILITY[unit.orders[0].ability.id]
        #     self.supply_pending += SUPPLY_PROVIDED.get(unit_morph, 0)

        await super().on_unit_type_changed(unit, previous_type)

    async def on_unit_created(self, unit: Unit):
        if unit.type_id is UnitTypeId.OVERLORD:
            if self.structures(WITH_TECH_EQUIVALENTS[UnitTypeId.LAIR]).exists:
                unit(AbilityId.BEHAVIOR_GENERATECREEPON)
        await super(self.__class__, self).on_unit_created(unit)

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float):
        if unit.type_id == UnitTypeId.OVERLORD:
            enemies = self.enemy_units | self.enemy_structures
            if enemies.exists:
                enemy = enemies.closest_to(unit)
                unit.move(unit.position.towards(enemy.position, -20))
            else:
                unit.move(unit.position.towards(self.start_location, 20))
        await super(self.__class__, self).on_unit_took_damage(unit, amount_damage_taken)

    async def corrosive_bile(self):

        def target_priority(target):
            priority = 10 + max(target.ground_dps, target.air_dps)
            # priority /= 100 + target.health + target.shield
            priority /= 2 + target.movement_speed
            return priority

        ability = AbilityId.EFFECT_CORROSIVEBILE
        ability_data = self.game_data.abilities[ability.value]._proto
        ravagers = self.units_by_type[UnitTypeId.RAVAGER]
        if not ravagers:
            return
        ravager_abilities = await self.get_available_abilities(ravagers)
        for ravager, abilities in zip(ravagers, ravager_abilities):
            if ability not in abilities:
                continue
            targets = (
                target
                for target in chain(self.all_enemy_units, self.destructables_filtered)
                if ravager.distance_to(target) <= ravager.radius + ability_data.cast_range
            )
            target = max(targets, key=target_priority, default=None)
            if target:
                ravager(ability, target=target.position)

    async def on_step(self, iteration):

        if iteration == 0:
            return

        # if 3.5 * 60 < self.time:
        #     await self.client.debug_leave()

        await super().on_step(iteration)

        steps = {
            self.update_tables: 1,
            self.extractor_trick: 1,
            # self.update_abilities: 1,
            # self.update_pending: 1,
            self.adjustComposition: 1,
            self.micro_queens: 1,
            self.spreadCreep: 1,
            # self.moveOverlord: 1,
            self.changelingScout: 1,
            self.morphOverlords: 1,
            self.morphUnits: 1,
            # self.trainQueens: 4,
            # self.tech: 4,
            self.upgrade: 1,
            self.expand: 1,
            self.micro: 1,
            self.assignWorker: 1,
            self.macro: 1,
            self.adjustGasTarget: 1,
            self.buildGasses: 1,
            self.corrosive_bile: 1,
        }

        steps_filtered = [s for s, m in steps.items() if iteration % m == 0]
            
        if self.timings_interval:
            timings = await run_timed(steps_filtered)
            for key, value in timings.items():
                self.timings_acc[key] = self.timings_acc.get(key, 0) + value
            if iteration % self.timings_interval == 0:
                timings_items = ((k, round(1e3 * n / self.timings_interval, 1)) for k, n in self.timings_acc.items())
                timings_sorted = dict(sorted(timings_items, key=lambda p : p[1], reverse=True))
                print(timings_sorted)
                # print(self.pending)
                # print(len(self.macroObjectives))
                self.timings_acc = {}
        else:
            for step in steps_filtered:
                result = step()
                if inspect.isawaitable(result):
                    result = await result
    def counterComposition(self, enemies: Dict[UnitTypeId, int]) -> Dict[UnitTypeId, int]:

        enemyValue = sum((self.unitValue(u) * n for u, n in enemies.items()))
        if enemyValue == 0:
            return {}, []
        weights = {
            u: sum((w * self.unitValue(v) * enemies[v] for v, w in vw.items()))
            for u, vw in UNIT_COUNTERS.items()
        }
        techTargets = []
        composition = {}
        weights = sorted(weights.items(), key=lambda p: p[1], reverse=True)
        for u, w in weights:
            if 0 < self.getTechDistance(u):
                techTargets.append(u)
                continue
            elif w <= 0 and 0 < len(composition):
                break
            composition[u] = max(1, w)
        weightSum = sum(composition.values())
        composition = {
            u: math.ceil((w  / weightSum) * (enemyValue / self.unitValue(u)))
            for u, w in composition.items()
        }

        return composition, techTargets

    def extractor_trick(self):
        if not self.extractor_trick_enabled:
            return
        extractors = [
            extractor
            for extractor in self.pending_by_type[UnitTypeId.EXTRACTOR]
            if extractor.type_id == UnitTypeId.EXTRACTOR
        ]
        if not self.supply_left and extractors:
            for extractor in extractors:
                extractor(AbilityId.CANCEL)
            self.extractor_trick_enabled = False

    def upgrades_by_unit(self, unit: UnitTypeId) -> Iterable[UpgradeId]:
        if unit == UnitTypeId.ZERGLING:
            return chain(
                (UpgradeId.ZERGLINGMOVEMENTSPEED, UpgradeId.ZERGLINGATTACKSPEED),
                self.upgradeSequence(ZERG_MELEE_UPGRADES),
                self.upgradeSequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.ULTRALISK:
            return chain(
                (UpgradeId.CHITINOUSPLATING, UpgradeId.ANABOLICSYNTHESIS),
                self.upgradeSequence(ZERG_MELEE_UPGRADES),
                self.upgradeSequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.BANELING:
            return chain(
                (UpgradeId.CENTRIFICALHOOKS,),
                self.upgradeSequence(ZERG_MELEE_UPGRADES),
                self.upgradeSequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.ROACH:
            return chain(
                (UpgradeId.GLIALRECONSTITUTION,),
                self.upgradeSequence(ZERG_RANGED_UPGRADES),
                self.upgradeSequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.HYDRALISK:
            return chain(
                (UpgradeId.EVOLVEGROOVEDSPINES, UpgradeId.EVOLVEMUSCULARAUGMENTS),
                self.upgradeSequence(ZERG_RANGED_UPGRADES),
                self.upgradeSequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.QUEEN:
            return chain(
                # self.upgradeSequence(ZERG_RANGED_UPGRADES),
                # self.upgradeSequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.MUTALISK:
            return chain(
                self.upgradeSequence(ZERG_FLYER_UPGRADES),
                self.upgradeSequence(ZERG_FLYER_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.CORRUPTOR:
            return chain(
                self.upgradeSequence(ZERG_FLYER_UPGRADES),
                self.upgradeSequence(ZERG_FLYER_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.BROODLORD:
            return chain(
                self.upgradeSequence(ZERG_FLYER_ARMOR_UPGRADES),
                self.upgradeSequence(ZERG_MELEE_UPGRADES),
                self.upgradeSequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.OVERSEER:
            return (UpgradeId.OVERLORDSPEED,)
        else:
            return []

    def upgrade(self):

        upgrades = set(chain(*(self.upgrades_by_unit(unit) for unit in self.composition)))
        targets = [
            *chain(*(REQUIREMENTS[unit] for unit in self.composition)),
            *chain(*(REQUIREMENTS[upgrade] for upgrade in upgrades)),
            *upgrades,
        ]

        for target in targets:
            if not sum(self.count(t) for t in WITH_TECH_EQUIVALENTS.get(target, { target })):
                self.add_macro_target(MacroTarget(target))

    def upgradeSequence(self, upgrades) -> Iterable[UpgradeId]:
        for upgrade in upgrades:
            if upgrade not in self.state.upgrades:
                return (upgrade,)
        return tuple()

    async def changelingScout(self):
        overseers = self.units(WITH_TECH_EQUIVALENTS[UnitTypeId.OVERSEER])
        if overseers.exists:
            overseer = overseers.random
            ability = AbilityId.SPAWNCHANGELING_SPAWNCHANGELING
            if ability in await self.get_available_abilities(overseer):
                overseer(ability)
        for chanceling_type in CHANGELINGS:
            for changeling in self.units_by_type[chanceling_type]:
                if not changeling.is_moving:
                    target = random.choice(self.expansion_locations_list)
                    changeling.move(target)

    def moveOverlord(self):

        for overlord in self.units_by_type[UnitTypeId.OVERLORD]:
            if not overlord.is_moving:
                overlord.move(self.structures.random.position)

    async def spreadCreep(self, spreader: Unit = None, numAttempts: int = 5):

        if not CREEP_ENABLED:
            return
        
        # find spreader
        if not spreader:
            tumors = self.structures(UnitTypeId.CREEPTUMORBURROWED)
            if not tumors.exists:
                return
            tumor_abilities = await self.get_available_abilities(self.structures(UnitTypeId.CREEPTUMORBURROWED))
            for tumor, abilities in zip(tumors, tumor_abilities):
                if not AbilityId.BUILD_CREEPTUMOR_TUMOR in abilities:
                    continue
                spreader = tumor
                break

        if spreader is None:
            return

        # find target
        targets = (
            *self.expansion_locations_list,
            *(r.top_center for r in self.game_info.map_ramps),
        )

        targets = [t for t in targets if not self.has_creep(t)]
        if not targets:
            return

        def weight(p):
            d = sum(t.distance_to(p) for t in self.townhalls)
            d = len(self.townhalls) * spreader.distance_to(p)
            return pow(10 + d, -2)
        
        target = sample(targets, key=weight)
        target = spreader.position.towards(target, CREEP_RANGE)

        tumorPlacement = None
        for _ in range(numAttempts):
            position = await self.find_placement(AbilityId.ZERGBUILD_CREEPTUMOR, target)
            if position is None:
                continue
            if self.is_blocking_base(position):
                continue
            tumorPlacement = position
            break
        if tumorPlacement is None:
            return

        spreader.build(UnitTypeId.CREEPTUMOR, tumorPlacement)

    def buildSpores(self):
        # if self.buildOrder:
        #     return
        sporeTime = {
            Race.Zerg: 8 * 60,
            Race.Protoss: 5 * 60,
            Race.Terran: 5 * 60,
        }
        if (
            sporeTime[self.enemy_race] < self.time
            and self.count(UnitTypeId.SPORECRAWLER) < self.townhalls.amount
        ):
            self.add_macro_target(MacroTarget(UnitTypeId.SPORECRAWLER))

    def enumerate_army(self):
        for unit in super().enumerate_army():
            if unit.type_id == UnitTypeId.QUEEN:
                if unit.tag in self.inject_assigments.keys():
                    continue
                elif unit in self.pending_by_type[UnitTypeId.CREEPTUMORQUEEN]:
                    continue
            yield unit

    async def micro_queens(self):

        queens_delete = set()
        for queen_tag, townhall_tag in self.inject_assigments.items():
            
            queen = self.units_by_tag.get(queen_tag)
            townhall = self.units_by_tag.get(townhall_tag)

            if not (queen and townhall):
                queens_delete.add(queen_tag)
            # elif not queen.is_idle:
            #     pass
            elif 7 < queen.distance_to(townhall):
                queen.attack(townhall.position)
            elif 25 <= queen.energy:
                queen(AbilityId.EFFECT_INJECTLARVA, townhall)

        for queen_tag in queens_delete:
            del self.inject_assigments[queen_tag]

        queens = sorted(self.units_by_type[UnitTypeId.QUEEN], key=lambda u:u.tag)
        townhalls = sorted(self.townhalls, key=lambda u:u.tag)

        queens_unassigned = [
            queen
            for queen in queens
            if not queen.tag in self.inject_assigments.keys()
        ]

        if len(self.inject_assigments) < self.inject_assigments_max:

            townhalls_unassigned = (
                townhall
                for townhall in townhalls
                if not townhall.tag in self.inject_assigments.values()
            )

            self.inject_assigments.update({
                queen.tag: townhall.tag
                for queen, townhall in zip(queens_unassigned, townhalls_unassigned)
            })

        queens_unassigned = [
            queen
            for queen in queens
            if not queen.tag in self.inject_assigments.keys()
        ]

        for queen in queens_unassigned:

            if queen in self.pending_by_type[UnitTypeId.CREEPTUMORQUEEN]:
                pass
            # elif queen.is_attacking:
            #     pass
            elif 25 <= queen.energy:
                await self.spreadCreep(queen)

    def adjustComposition(self):

        worker_limit = 80
        worker_target = min(worker_limit, self.getMaxWorkers())
        self.composition = {
            UnitTypeId.DRONE: worker_target,
            UnitTypeId.QUEEN: 1 + min(self.inject_assigments_max, self.townhalls.amount),
        }
        worker_count = self.count(UnitTypeId.DRONE, include_planned=False)
        ratio = pow(worker_count / worker_limit, 2)

        self.destroy_destructables = self.tech_time < self.time
    
        if self.time < self.tech_time:
            pass
        elif not self.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL2, include_planned=False):
            self.composition[UnitTypeId.OVERSEER] = 1
            self.composition[UnitTypeId.ROACH] = int(ratio * 60)
            self.composition[UnitTypeId.RAVAGER] = int(ratio * 10)
        elif not self.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL3, include_planned=False):
            self.composition[UnitTypeId.OVERSEER] = 1
            self.composition[UnitTypeId.ROACH] = 40
            self.composition[UnitTypeId.RAVAGER] = 10
            self.composition[UnitTypeId.HYDRALISK] = 20
        else:
            self.composition[UnitTypeId.OVERSEER] = 1
            self.composition[UnitTypeId.ROACH] = 40
            self.composition[UnitTypeId.RAVAGER] = 10
            self.composition[UnitTypeId.HYDRALISK] = 20
            self.composition[UnitTypeId.CORRUPTOR] = 3
            self.composition[UnitTypeId.BROODLORD] = 10

    def adjustGasTarget(self):

        cost_zero = Cost(0, 0, 0)
        cost_sum = sum((target.cost or cost_zero for target in self.macro_targets), cost_zero)

        minerals = max(0, cost_sum.minerals - self.minerals)
        vespene = max(0, cost_sum.vespene - self.vespene)
        if 7 * 60 < self.time and (minerals + vespene) == 0:
            gas_ratio = 6 / 22
        else:
            gas_ratio = vespene / max(1, vespene + minerals)
        self.gas_target = gas_ratio * self.count(UnitTypeId.DRONE, include_planned=False)
        self.gas_target = 3 * math.ceil(self.gas_target / 3)

    def buildGasses(self):
        gas_depleted = self.gas_buildings.filter(lambda g : not g.has_vespene).amount
        gas_have = self.count(UnitTypeId.EXTRACTOR) - gas_depleted
        gas_max = sum(1 for g in self.get_owned_geysers())
        gas_want = min(gas_max, math.ceil(self.gas_target / 3))
        for i in range(gas_want - gas_have):
            self.add_macro_target(MacroTarget(UnitTypeId.EXTRACTOR, priority=1))

    def morphOverlords(self):
        if 200 <= self.supply_cap:
            return
        supply_pending = sum(
            provided * self.count(unit, include_actual=False)
            for unit, provided in SUPPLY_PROVIDED.items()
        )
        if 200 <= self.supply_cap + supply_pending:
            return
        supply_buffer = 3 * (self.townhalls.amount + len(self.inject_assigments))
        if self.supply_left + supply_pending < supply_buffer:
            self.add_macro_target(MacroTarget(UnitTypeId.OVERLORD, priority=1))

    def expand(self, saturation_target: float = .9):
        
        worker_max = self.getMaxWorkers()
        if (
            not self.count(UnitTypeId.HATCHERY, include_actual=False)
            and not self.townhalls.not_ready.exists
            and saturation_target * worker_max <= self.count(UnitTypeId.DRONE, include_planned=False)
        ):
            self.add_macro_target(MacroTarget(UnitTypeId.HATCHERY, priority=1))

    def morphUnits(self):
        

        if self.supply_used == 200:
            return

        composition_have = {
            unit: self.count(unit)
            for unit in self.composition.keys()
        }

        # composition_missing = {
        #     unit: count - composition_have[unit]
        #     for unit, count in self.composition.items()
        # }

        targets = [
            MacroTarget(unit, priority = -(composition_have[unit] + 1) / count)
            # MacroTarget(unit, -random.random())
            for unit, count in self.composition.items()
            if composition_have[unit] < count
            # for i in range(int(count))
        ]

        for target in targets:

            if not any(self.get_missing_requirements(target.item, include_pending=False, include_planned=False)):
                self.add_macro_target(target)

            # requirement_missing = False
            # for requirement in REQUIREMENTS[target.item]:
            #     if not sum(
            #         self.count(equivalent, include_pending=False, include_planned=False)
            #         for equivalent in WITH_TECH_EQUIVALENTS[requirement]
            #     ):
            #         requirement_missing = True
            #         break

            # if not requirement_missing:

        
        # if 3 < self.townhalls.amount:
        #     for unit in self.composition.keys():
        #         for plan in self.planned_by_type[unit]:
        #             plan.priority = -random.random()