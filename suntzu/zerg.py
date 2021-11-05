
from collections import defaultdict
import inspect
import math
import itertools, random
import build
import numpy as np
from typing import Counter, Iterable, List, Coroutine, Dict, Set, Union, Tuple
from itertools import chain

from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.unit import Unit
from sc2.data import Race, race_townhalls, race_worker, Result
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.position import Point2

from .strategies.gasless import GasLess
from .strategies.roach_rush import RoachRush
from .strategies.hatch_first import HatchFirst
from .strategies.zerg_strategy import ZergStrategy
from .timer import run_timed
from .constants import CHANGELINGS, SUPPLY_PROVIDED
from .common import CommonAI, PerformanceMode
from .utils import sample
from .constants import BUILD_ORDER_PRIORITY, WITH_TECH_EQUIVALENTS, REQUIREMENTS, ZERG_ARMOR_UPGRADES, ZERG_MELEE_UPGRADES, ZERG_RANGED_UPGRADES, ZERG_FLYER_UPGRADES, ZERG_FLYER_ARMOR_UPGRADES
from .cost import Cost
from .macro_plan import MacroPlan

CREEP_RANGE = 10
CREEP_ENABLED = True

SPORE_TIMING = {
    Race.Zerg: 7 * 60,
    Race.Protoss: 4.5 * 60,
    Race.Terran: 4.5 * 60,
}

TIMING_INTERVAL = 64

class ZergAI(CommonAI):

    def __init__(self, strategy: ZergStrategy = None, **kwargs):
        super(self.__class__, self).__init__(**kwargs)

        # strategy = HatchFirst()

        if not strategy:
            strategy_types = [RoachRush, HatchFirst]
            strategy_type = sample(strategy_types)
            strategy = strategy_type()

        self.strategy: ZergStrategy = strategy
        self.tags.append(self.strategy.name())
        self.composition: Dict[UnitTypeId, int] = dict()
        self.timings_acc = dict()
        self.inject_assigments = dict()
        self.inject_assigments_max = 5

    def destroy_destructables(self):
        return self.strategy.destroy_destructables(self)

    async def on_start(self):
        for step in self.strategy.build_order():
            self.add_macro_plan(MacroPlan(step, priority=BUILD_ORDER_PRIORITY))
        return await super().on_start()

    async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId):
        if unit.type_id == UnitTypeId.LAIR:
            ability = AbilityId.BEHAVIOR_GENERATECREEPON
            overlords = [
                self.observation.unit_by_tag.get(t)
                for t in self.observation.actual_by_type[UnitTypeId.OVERLORD]
            ]
            for overlord in overlords:
                if not overlord:
                    continue
                if ability in await self.get_available_abilities(overlord):
                    overlord(ability)
        return await super().on_unit_type_changed(unit, previous_type)

    async def on_unit_created(self, unit: Unit):
        if unit.type_id is UnitTypeId.OVERLORD:
            if self.structures(WITH_TECH_EQUIVALENTS[UnitTypeId.LAIR]).exists:
                unit(AbilityId.BEHAVIOR_GENERATECREEPON)
        return await super(self.__class__, self).on_unit_created(unit)

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float):
        if unit.type_id == UnitTypeId.OVERLORD:
            enemies = self.enemy_units | self.enemy_structures
            if enemies.exists:
                enemy = enemies.closest_to(unit)
                unit.move(unit.position.towards(enemy.position, -20))
            else:
                unit.move(unit.position.towards(self.start_location, 20))
        return await super(self.__class__, self).on_unit_took_damage(unit, amount_damage_taken)

    async def transfuse(self):

        ability = AbilityId.TRANSFUSION_TRANSFUSION
        queens = list(self.observation.unit_by_tag[t] for t in self.observation.actual_by_type[UnitTypeId.QUEEN])
        if not any(queens):
            return
        queens_abilities = await self.get_available_abilities(queens)

        def priority(queen: Unit, target: Unit) -> float:
            if queen.tag == target.tag:
                return 0
            if not queen.in_ability_cast_range(ability, target):
                return 0
            # if BuffId.TRANSFUSION in target.buffs:
            #     return 0
            if target.health_max <= target.health + 75:
                return 0
            priority = 1
            priority *= 10 + target.health_max - target.health
            return priority

        for queen, abilities in zip(queens, queens_abilities):

            if ability not in abilities:
                continue

            target = max(self.all_own_units, key = lambda t : priority(queen, t))
            if priority(queen, target) <= 0:
                continue

            queen(ability, target=target)

    async def corrosive_bile(self):

        def target_priority(target):
            priority = 10 + max(target.ground_dps, target.air_dps)
            priority /= 100 + target.health + target.shield
            priority /= 2 + target.movement_speed
            return priority

        ability = AbilityId.EFFECT_CORROSIVEBILE
        ability_data = self.game_data.abilities[ability.value]._proto
        ravagers = [
            self.observation.unit_by_tag[t]
            for t in self.observation.actual_by_type[UnitTypeId.RAVAGER]
        ]
        if not ravagers:
            return
        ravager_abilities = await self.get_available_abilities(ravagers)
        for ravager, abilities in zip(ravagers, ravager_abilities):
            if ability not in abilities:
                continue
            targets = (
                target
                for target in chain(self.all_enemy_units, self.observation.destructables)
                if ravager.distance_to(target) <= ravager.radius + ability_data.cast_range
            )
            target: Unit = max(targets, key=target_priority, default=None)
            if not target:
                continue
            previous_position = self.enemy_positions.get(target.tag)
            # if previous_position:
            #     velocity = 22.4 * (target.position - previous_position) / (self.game_step)
            #     predicted_position = target.position + 2.5 * velocity
            # else:
            predicted_position = target.position
            ravager(ability, target=predicted_position)

    def update_strategy(self):
        self.strategy.update(self)

    def get_gas_target(self):
        gas_target = self.strategy.gas_target(self)
        if gas_target == None:
            gas_target = super().get_gas_target()
        return gas_target

    async def on_step(self, iteration):

        await super(self.__class__, self).on_step(iteration)

        if iteration == 0:
            return

        steps = {
            self.update_observation: 1,
            self.update_bases: 1,
            self.update_composition: 1,
            self.update_gas: 16,
            self.micro_queens: 1,
            self.spread_creep: 1,
            self.scout: 1,
            self.morph_overlords: 1,
            self.make_composition: 1,
            self.upgrade: 1,
            self.expand: 1,
            self.micro: 1,
            self.macro: 1,
            self.transfuse: 1,
            self.corrosive_bile: 1,
            self.update_strategy: 1,
            self.save_enemy_positions: 1,
        }

        steps_filtered = [s for s, m in steps.items() if iteration % m == 0]
            
        if self.debug:
            timings = await run_timed(steps_filtered)
            for key, value in timings.items():
                self.timings_acc[key] = self.timings_acc.get(key, 0) + value
            if iteration % TIMING_INTERVAL == 0:
                timings_items = ((k, round(1e3 * n / TIMING_INTERVAL, 1)) for k, n in self.timings_acc.items())
                timings_sorted = dict(sorted(timings_items, key=lambda p : p[1], reverse=True))
                print(timings_sorted)
                self.timings_acc = {}
        else:
            for step in steps_filtered:
                result = step()
                if inspect.isawaitable(result):
                    result = await result

    def upgrades_by_unit(self, unit: UnitTypeId) -> Iterable[UpgradeId]:
        if unit == UnitTypeId.ZERGLING:
            return chain(
                (UpgradeId.ZERGLINGMOVEMENTSPEED, UpgradeId.ZERGLINGATTACKSPEED),
                self.upgrade_sequence(ZERG_MELEE_UPGRADES),
                self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.ULTRALISK:
            return chain(
                (UpgradeId.CHITINOUSPLATING, UpgradeId.ANABOLICSYNTHESIS),
                self.upgrade_sequence(ZERG_MELEE_UPGRADES),
                self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.BANELING:
            return chain(
                (UpgradeId.CENTRIFICALHOOKS,),
                self.upgrade_sequence(ZERG_MELEE_UPGRADES),
                self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.ROACH:
            return chain(
                (UpgradeId.GLIALRECONSTITUTION,),
                self.upgrade_sequence(ZERG_RANGED_UPGRADES),
                self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.HYDRALISK:
            return chain(
                (UpgradeId.EVOLVEGROOVEDSPINES, UpgradeId.EVOLVEMUSCULARAUGMENTS),
                self.upgrade_sequence(ZERG_RANGED_UPGRADES),
                self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.QUEEN:
            return chain(
                # self.upgradeSequence(ZERG_RANGED_UPGRADES),
                # self.upgradeSequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.MUTALISK:
            return chain(
                self.upgrade_sequence(ZERG_FLYER_UPGRADES),
                self.upgrade_sequence(ZERG_FLYER_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.CORRUPTOR:
            return chain(
                self.upgrade_sequence(ZERG_FLYER_UPGRADES),
                self.upgrade_sequence(ZERG_FLYER_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.BROODLORD:
            return chain(
                self.upgrade_sequence(ZERG_FLYER_ARMOR_UPGRADES),
                self.upgrade_sequence(ZERG_MELEE_UPGRADES),
                self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.OVERSEER:
            return (UpgradeId.OVERLORDSPEED,)
        else:
            return []

    def upgrade(self):
        upgrades = chain(*(self.upgrades_by_unit(unit) for unit in self.composition))
        upgrades = list(dict.fromkeys(upgrades))
        targets = (
            *chain(*(REQUIREMENTS[unit] for unit in self.composition)),
            *chain(*(REQUIREMENTS[upgrade] for upgrade in upgrades)),
            *upgrades,
        )
        targets = list(dict.fromkeys(targets))
        for target in targets:
            if not sum(self.observation.count(t) for t in WITH_TECH_EQUIVALENTS.get(target, { target })):
                self.add_macro_plan(MacroPlan(target))

    def upgrade_sequence(self, upgrades) -> Iterable[UpgradeId]:
        for upgrade in upgrades:
            if upgrade not in self.state.upgrades:
                return (upgrade,)
        return tuple()

    async def scout(self):
        overseers = self.units(WITH_TECH_EQUIVALENTS[UnitTypeId.OVERSEER])
        if overseers.exists:
            overseer = overseers.random
            ability = AbilityId.SPAWNCHANGELING_SPAWNCHANGELING
            if ability in await self.get_available_abilities(overseer):
                overseer(ability)
        changelings = [
            self.observation.unit_by_tag[t]
            for tt in CHANGELINGS
            for t in self.observation.actual_by_type[tt]
        ]
        for changeling in changelings:
            if not changeling:
                continue
            if not changeling.is_moving:
                target = random.choice(self.expansion_locations_list)
                changeling.move(target)
        # overlords = [
        #     self.observation.unit_by_tag[t]
        #     for t in self.observation.actual_by_type[UnitTypeId.OVERLORD]
        # ]
        # for overlord in overlords:
        #     if not overlord.is_moving:
        #         target = self.structures.random
        #         if 1 < overlord.distance_to(target):
        #             overlord.move(target.position)

    async def spread_creep(self, spreader: Unit = None, numAttempts: int = 5):
        
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

        targets = [
            t
            for t in targets
            if self.in_placement_grid(t) and not self.has_creep(t) 
        ]
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
            position = await self.find_placement(AbilityId.ZERGBUILD_CREEPTUMOR, target, max_distance=12, placement_step=3)
            if position is None:
                continue
            if self.blocked_base(position):
                continue 
            tumorPlacement = position
            break
        if tumorPlacement is None:
            return

        spreader.build(UnitTypeId.CREEPTUMOR, tumorPlacement)

    def build_spores(self):
        sporeTime = {
            Race.Zerg: 8 * 60,
            Race.Protoss: 5 * 60,
            Race.Terran: 5 * 60,
        }
        if (
            sporeTime[self.enemy_race] < self.time
            and self.observation.count(UnitTypeId.SPORECRAWLER) < self.townhalls.amount
        ):
            self.add_macro_plan(MacroPlan(UnitTypeId.SPORECRAWLER))

    def enumerate_army(self):
        for unit in super().enumerate_army():
            if unit.type_id == UnitTypeId.QUEEN:
                if unit.tag in self.inject_assigments.keys():
                    continue
                elif any(o.ability.exact_id == AbilityId.BUILD_CREEPTUMOR_QUEEN for o in unit.orders):
                    continue
                elif unit in self.observation.pending_by_type[UnitTypeId.CREEPTUMORQUEEN]:
                    continue
            yield unit

    async def micro_queens(self):

        queens_delete = set()
        for queen_tag, townhall_tag in self.inject_assigments.items():
            
            queen = self.observation.unit_by_tag.get(queen_tag)
            townhall = self.observation.unit_by_tag.get(townhall_tag)

            if not (queen and townhall):
                queens_delete.add(queen_tag)
            # elif not queen.is_idle:
            #     pass
            elif 7 < queen.position.distance_to(townhall.position):
                queen.attack(townhall.position)
            elif 25 <= queen.energy:
                queen(AbilityId.EFFECT_INJECTLARVA, townhall)

        for queen_tag in queens_delete:
            del self.inject_assigments[queen_tag]

        queens = sorted((self.observation.unit_by_tag[t] for t in self.observation.actual_by_type[UnitTypeId.QUEEN]), key=lambda u:u.tag)
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

        if not CREEP_ENABLED:
            return

        queens_unassigned = [
            queen
            for queen in queens
            if not queen.tag in self.inject_assigments.keys()
        ]

        for queen in queens_unassigned:

            if any(o.ability.exact_id == AbilityId.BUILD_CREEPTUMOR_QUEEN for o in queen.orders):
                pass
            # if queen in self.observation.pending_by_type[UnitTypeId.CREEPTUMORQUEEN]:
            #     pass
            # elif queen.is_attacking:
            #     pass
            elif 25 <= queen.energy:
                await self.spread_creep(queen)

    def update_composition(self):
        self.composition = self.strategy.composition(self)

    def morph_overlords(self):
        if 200 <= self.supply_cap:
            return
        supply_pending = sum(
            provided * self.observation.count(unit, include_actual=False)
            for unit, provided in SUPPLY_PROVIDED.items()
        )
        if 200 <= self.supply_cap + supply_pending:
            return
        supply_buffer = 3 * (self.townhalls.amount + len(self.inject_assigments))
        if self.supply_left + supply_pending < supply_buffer:
            self.add_macro_plan(MacroPlan(UnitTypeId.OVERLORD, priority=1))

    def expand(self, saturation_target: float = .9):
        
        worker_max = self.get_max_harvester()
        if (
            not self.observation.count(UnitTypeId.HATCHERY, include_actual=False)
            and not self.townhalls.not_ready.exists
            and saturation_target * worker_max <= self.observation.count(UnitTypeId.DRONE, include_planned=False)
        ):
            self.add_macro_plan(MacroPlan(UnitTypeId.HATCHERY, priority=1))