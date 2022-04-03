
from collections import defaultdict
import datetime
import inspect
import math
import itertools, random
import numpy as np
from typing import Counter, Iterable, List, Coroutine, Dict, Set, Union, Tuple, Optional, Type
from itertools import chain

from sc2.unit import Unit
from sc2.data import Race, race_townhalls
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from src.strategies.fast_lair import FastLair
from src.strategies.muta import Muta

from .unit_counters import UNIT_COUNTER_MATRIX
from .strategies.hatch_first import HatchFirst
from .strategies.zerg_strategy import ZergStrategy
from .constants import SUPPLY_PROVIDED
from .ai_base import AIBase
from .utils import armyValue, center, sample, unitValue, run_timed
from .constants import BUILD_ORDER_PRIORITY, WITH_TECH_EQUIVALENTS, REQUIREMENTS, ZERG_ARMOR_UPGRADES, ZERG_MELEE_UPGRADES, ZERG_RANGED_UPGRADES, ZERG_FLYER_UPGRADES, ZERG_FLYER_ARMOR_UPGRADES
from .cost import Cost
from .macro_plan import MacroPlan
from .modules.creep import Creep

import cProfile
import pstats

import matplotlib.pyplot as plt

SPORE_TRIGGERS: Dict[Race, Set[UnitTypeId]] = {
    Race.Zerg: {
        UnitTypeId.DRONEBURROWED,
        UnitTypeId.QUEENBURROWED,
        UnitTypeId.ZERGLINGBURROWED,
        UnitTypeId.BANELINGBURROWED,
        UnitTypeId.ROACHBURROWED,
        UnitTypeId.RAVAGERBURROWED,
        UnitTypeId.HYDRALISKBURROWED,
        UnitTypeId.LURKERMP,
        UnitTypeId.LURKERMPBURROWED,
        UnitTypeId.INFESTORBURROWED,
        UnitTypeId.SWARMHOSTBURROWEDMP,
        UnitTypeId.ULTRALISKBURROWED,
        UnitTypeId.MUTALISK,
        UnitTypeId.SPIRE,
    },
    Race.Protoss: {
        UnitTypeId.STARGATE,
        UnitTypeId.ORACLE,
        UnitTypeId.VOIDRAY,
        UnitTypeId.CARRIER,
        UnitTypeId.TEMPEST,
        UnitTypeId.PHOENIX,
    },
    Race.Terran: {
        UnitTypeId.STARPORT,
        UnitTypeId.STARPORTFLYING,
        UnitTypeId.MEDIVAC,
        UnitTypeId.LIBERATOR,
        UnitTypeId.RAVEN,
        UnitTypeId.BANSHEE,
        UnitTypeId.BATTLECRUISER,
        UnitTypeId.WIDOWMINE,
        UnitTypeId.WIDOWMINEBURROWED,
    },
}
SPORE_TRIGGERS[Race.Random] = set((v for vs in SPORE_TRIGGERS.values() for v in vs))

TIMING_INTERVAL = 64

class ZergAI(AIBase):

    def __init__(self, strategy_cls: Type[ZergStrategy] = None):
        super().__init__()

        self.strategy_cls: Optional[Type[ZergStrategy]] = strategy_cls
        self.composition: Dict[UnitTypeId, int] = dict()

        self.build_spores: bool = False
        self.build_spines: bool = False

    async def on_start(self):

        if not self.strategy_cls:
            if self.enemy_race == Race.Terran:
                self.strategy_cls = FastLair
            else:
                self.strategy_cls = HatchFirst
        self.strategy: ZergStrategy = self.strategy_cls(self)

        for step in self.strategy.build_order():
            if isinstance(step, MacroPlan):
                plan = step
            else:
                plan = MacroPlan(step)
            plan.priority = plan.priority or BUILD_ORDER_PRIORITY
            if step in race_townhalls[self.race]:
                plan.max_distance = 0
            self.add_macro_plan(plan)

        await super().on_start()

    async def on_before_start(self):
        return await super().on_before_start()

    async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId):
        if unit.type_id == UnitTypeId.CREEPTUMORBURROWED:
            self.creep.tumor_front[unit.tag] = self.state.game_loop
        return await super().on_unit_type_changed(unit, previous_type)

    async def on_building_construction_started(self, unit: Unit):
        return await super().on_building_construction_started(unit)

    async def on_building_construction_complete(self, unit: Unit):
        return await super().on_building_construction_complete(unit)

    async def on_unit_destroyed(self, unit_tag: int):
        return await super().on_unit_destroyed(unit_tag)

    async def on_unit_created(self, unit: Unit):
        return await super().on_unit_created(unit)

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float):
        return await super().on_unit_took_damage(unit, amount_damage_taken)

    async def on_step(self, iteration):

        if iteration == 0:
            return

        # if 1 < self.time:
        #     await self.chat.add_tag(self.version, False)
        #     await self.chat.add_tag(self.strategy.name, False)

        await super().on_step(iteration)

        self.strategy.update()
        self.morph_overlords()
        self.make_defenses()
        self.make_tech()
        self.expand()

    def upgrades_by_unit(self, unit: UnitTypeId) -> Iterable[UpgradeId]:
        if unit == UnitTypeId.ZERGLING:
            return chain(
                (UpgradeId.ZERGLINGMOVEMENTSPEED,),
                # (UpgradeId.ZERGLINGMOVEMENTSPEED, UpgradeId.ZERGLINGATTACKSPEED),
                # self.upgrade_sequence(ZERG_MELEE_UPGRADES),
                # self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
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
                (UpgradeId.GLIALRECONSTITUTION,
                UpgradeId.BURROW,
                UpgradeId.TUNNELINGCLAWS),
                # (UpgradeId.GLIALRECONSTITUTION,),
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

    def make_tech(self):
        upgrades = chain(*(self.upgrades_by_unit(unit) for unit in self.composition))
        upgrades = list(dict.fromkeys(upgrades))
        upgrades = [u for u in upgrades if self.strategy.filter_upgrade(u)]
        targets = (
            *upgrades,
            *chain(*(REQUIREMENTS[unit] for unit in self.composition)),
            *chain(*(REQUIREMENTS[upgrade] for upgrade in upgrades)),
        )
        targets = list(dict.fromkeys(targets))
        for target in targets:
            equivalents =  WITH_TECH_EQUIVALENTS.get(target, { target })
            if sum(self.count(t) for t in equivalents) == 0:
                self.add_macro_plan(MacroPlan(target, priority=-1/3))

    def upgrade_sequence(self, upgrades) -> Iterable[UpgradeId]:
        for upgrade in upgrades:
            if not self.count(upgrade, include_planned=False):
                return (upgrade,)
        return tuple()

    def make_defenses(self):

        for unit_type in SPORE_TRIGGERS[self.enemy_race]:
            if any(self.enemies_by_type[unit_type]):
                self.build_spores = True

        for i, base in enumerate(self.bases):
            targets: Dict[UnitTypeId, int] = dict()
            if self.build_spores:
                targets[UnitTypeId.SPORECRAWLER] = 1
                # if self.enemy_race == Race.Terran:
                #     targets[UnitTypeId.SPORECRAWLER] += 1
            if (
                1 <= i
                and base.townhall
                and self.build_spines
                # and 1 <= self.count(UnitTypeId.SPAWNINGPOOL, include_pending=False, include_planned=False)
                # and self.block_manager.enemy_base_count <= 1
            ):
                targets[UnitTypeId.SPINECRAWLER] = 1
            base.defensive_targets = targets

    def morph_overlords(self):
        if 200 <= self.supply_cap:
            return
        supply_pending = sum(
            provided * self.count(unit, include_actual=False)
            for unit, provided in SUPPLY_PROVIDED.items()
        )
        if 200 <= self.supply_cap + supply_pending:
            return
        # income = self.state.score.collection_rate_minerals + self.state.score.collection_rate_vespene
        # supply_buffer = income / 300

        supply_buffer = 6
        supply_buffer += 2 * self.townhalls.amount
        supply_buffer += 2 * len(self.unit_manager.inject_queens)
        
        if self.supply_left + supply_pending < supply_buffer:
            self.add_macro_plan(MacroPlan(UnitTypeId.OVERLORD, priority=1))

    def expand(self):

        # if self.scout_manager.enemy_base_count + 1 <= self.townhalls.amount:
        #     return

        if self.count(UnitTypeId.SPAWNINGPOOL, include_pending=False, include_planned=False) < 1:
            return
        
        worker_max = self.get_max_harvester()
        saturation = self.state.score.food_used_economy / max(1, worker_max)
        saturation = max(0, min(1, saturation))
        priority = 3 * (saturation - 1)

        for plan in self.planned_by_type[UnitTypeId.HATCHERY]:
            if plan.priority < BUILD_ORDER_PRIORITY:
                plan.priority = priority

        if -1 < priority and self.count(UnitTypeId.HATCHERY, include_actual=False) < 1:
            plan = MacroPlan(UnitTypeId.HATCHERY)
            plan.priority = priority
            plan.max_distance = 0
            self.add_macro_plan(plan)