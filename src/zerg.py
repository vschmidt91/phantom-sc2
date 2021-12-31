
from collections import defaultdict
import inspect
import math
import itertools, random
import numpy as np
from typing import Counter, Iterable, List, Coroutine, Dict, Set, Union, Tuple, Optional
from itertools import chain
from sc2 import unit

from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.unit import Unit
from sc2.data import Race, race_townhalls, race_worker, Result
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.position import Point2
from sc2.unit_command import UnitCommand

from .unit_counters import UNIT_COUNTERS
from .behaviors.behavior import Behavior, BehaviorSelector, BehaviorSequence
from .behaviors.burrow import BurrowBehavior
from .behaviors.fight import FightBehavior
from .behaviors.dodge import DodgeBehavior
from .behaviors.search import SearchBehavior
from .behaviors.gather import GatherBehavior
from .behaviors.survive import SurviveBehavior
from .behaviors.launch_corrosive_biles import LaunchCorrosiveBilesBehavior
from .behaviors.transfuse import TransfuseBehavior
from .behaviors.unit_manager import UnitManager
from .strategies.gasless import GasLess
from .strategies.roach_rush import RoachRush
from .strategies.hatch_first import HatchFirst
from .strategies.pool12 import Pool12
from .strategies.zerg_strategy import ZergStrategy
from .timer import run_timed
from .constants import CHANGELINGS, CREEP_ABILITIES, SUPPLY_PROVIDED
from .ai_base import AIBase, PerformanceMode
from .utils import armyValue, center, sample, unitValue
from .constants import BUILD_ORDER_PRIORITY, WITH_TECH_EQUIVALENTS, REQUIREMENTS, ZERG_ARMOR_UPGRADES, ZERG_MELEE_UPGRADES, ZERG_RANGED_UPGRADES, ZERG_FLYER_UPGRADES, ZERG_FLYER_ARMOR_UPGRADES
from .cost import Cost
from .macro_plan import MacroPlan

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
    },
}
SPORE_TRIGGERS[Race.Random] = set((v for vs in SPORE_TRIGGERS.values() for v in vs))

TIMING_INTERVAL = 64

class ZergAI(AIBase):

    def __init__(self, strategy: ZergStrategy = None, **kwargs):
        super(self.__class__, self).__init__(**kwargs)

        self.strategy: Optional[ZergStrategy] = strategy
        self.composition: Dict[UnitTypeId, int] = dict()

        self.creep_area_min: np.ndarray = None
        self.creep_area_max: np.ndarray = None
        self.creep_coverage: float = 0
        self.creep_tile_count: int = 1
        self.build_spores: bool = False
        self.extractor_trick_enabled: bool = False

    async def micro(self):
        await super().micro()

        if self.debug and self.state.game_loop % 1000 == 0:

            with cProfile.Profile() as pr:
                self.unit_manager.execute()

            stats = pstats.Stats(pr)
            stats.sort_stats(pstats.SortKey.TIME)
            stats.dump_stats(filename='profiling.prof')

        else:

            self.unit_manager.execute()

    def handle_actions(self):
        for action in self.state.actions_unit_commands:
            if action.exact_id == AbilityId.BUILD_CREEPTUMOR_TUMOR:
                self.tumor_front_tags.difference_update(action.unit_tags)
        return super().handle_actions()

    def counter_composition(self, enemies: Iterable[Unit]) -> Dict[UnitTypeId, int]:

        def value(unit: UnitTypeId):
            cost = self.cost[unit]
            return cost.minerals + cost.vespene

        if not any(enemies):
            return {
                UnitTypeId.ZERGLING: 1,
                UnitTypeId.OVERSEER: 1
            }

        enemies_by_type = defaultdict(lambda: set())
        for enemy in enemies:
            enemies_by_type[enemy.type_id].add(enemy)

        enemy_cost = sum(
            (self.cost[enemy_type] * len(n)
            for enemy_type, n in enemies_by_type.items()
            if enemy_type in self.cost)
        , Cost(0, 0, 0))
        enemy_value = enemy_cost.minerals + enemy_cost.vespene

        weights = {
            unit: sum(
                w * len(enemies_by_type[e])
                for e, w in UNIT_COUNTERS[unit].items()
            )
            for unit in UNIT_COUNTERS.keys()
        }

        weights = sorted(weights.items(),
            key = lambda p : p[1],
            reverse = True)

        best_unit, _ = weights[0]
        best_can_build = next(
            (u for u, _ in weights if not any(self.get_missing_requirements(u, include_pending=False, include_planned=False))),
            None)

        if best_unit == best_can_build:
            return {
                best_unit: math.ceil(enemy_value / value(best_unit))
            }
        else:
            return {
                best_unit: 0,
                best_can_build: math.ceil(enemy_value / value(best_can_build))
            }

    def destroy_destructables(self):
        return self.strategy.destroy_destructables(self)

    async def on_start(self):

        if not self.strategy:
            strategy_classes = [
                HatchFirst,
                RoachRush
            ]
            if self.enemy_race == Race.Protoss:
                strategy_classes.append(Pool12)
            self.strategy = random.choice(strategy_classes)()

        for step in self.strategy.build_order():
            plan = MacroPlan(step)
            plan.priority = BUILD_ORDER_PRIORITY
            if step in race_townhalls[self.race]:
                plan.max_distance = 0
            self.add_macro_plan(plan)

        await super().on_start()

        self.creep_area_min = np.array(self.game_info.map_center)
        self.creep_area_max = np.array(self.game_info.map_center)
        for base in self.expansion_locations_list:
            self.creep_area_min = np.minimum(self.creep_area_min, base)
            self.creep_area_max = np.maximum(self.creep_area_max, base)

        self.creep_tile_count = np.sum(self.game_info.pathing_grid.data_numpy)

    async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId):
        return await super().on_unit_type_changed(unit, previous_type)

    async def on_building_construction_started(self, unit: Unit):
        if unit.type_id in {
            UnitTypeId.CREEPTUMOR,
            UnitTypeId.CREEPTUMORQUEEN,
            UnitTypeId.CREEPTUMORBURROWED
        }:
            self.tumor_front_tags.add(unit.tag)
        return await super().on_building_construction_started(unit)

    async def on_building_construction_complete(self, unit: Unit):
        return await super().on_building_construction_complete(unit)

    async def on_unit_destroyed(self, unit_tag: int):
        return await super().on_unit_destroyed(unit_tag)

    async def on_unit_created(self, unit: Unit):
        return await super(self.__class__, self).on_unit_created(unit)

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float):
        return await super(self.__class__, self).on_unit_took_damage(unit, amount_damage_taken)

    def update_strategy(self):
        self.strategy.update(self)

    def get_gas_target(self):
        gas_target = self.strategy.gas_target(self)
        if gas_target == None:
            gas_target = super().get_gas_target()
        return gas_target

    def extractor_trick(self):
        if not self.extractor_trick_enabled:
            return
        if 0 < self.supply_left:
            return
        extractor = next(iter(self.pending_by_type[UnitTypeId.EXTRACTOR]), None)
        if not extractor:
            return
        extractor(AbilityId.CANCEL)
        self.extractor_trick_enabled = False

    async def on_step(self, iteration):

        await super(self.__class__, self).on_step(iteration)

        if iteration == 0:
            return

        if 1 < self.time:
            await self.add_tag(self.version, False)
            await self.add_tag(type(self.strategy).__name__, False)

        steps = self.strategy.steps(self)

        self.extractor_trick()
            
        for step, m in steps.items():
            if iteration % m != 0:
                continue
            result = step()
            if inspect.isawaitable(result):
                result = await result

    def draw_debug(self):
        if not self.debug:
            return
        self.client.debug_text_screen(f'Creep Coverage: {round(100 * self.creep_coverage)}%', (0.01, 0.05))
        return super().draw_debug()

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
                # (UpgradeId.GLIALRECONSTITUTION,
                # UpgradeId.BURROW,
                # UpgradeId.TUNNELINGCLAWS),
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

    def make_tech(self):
        upgrades = chain(*(self.upgrades_by_unit(unit) for unit in self.composition))
        upgrades = list(dict.fromkeys(upgrades))
        upgrades = [u for u in upgrades if self.strategy.filter_upgrade(self, u)]
        targets = (
            *chain(*(REQUIREMENTS[unit] for unit in self.composition)),
            *chain(*(REQUIREMENTS[upgrade] for upgrade in upgrades)),
            *upgrades,
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

    def update_composition(self):
        self.composition = self.strategy.composition(self)

    def make_defenses(self):

        for unit_type in SPORE_TRIGGERS[self.enemy_race]:
            if any(self.enemies_by_type[unit_type]):
                self.build_spores = True

        if self.build_spores:
            for base in self.bases:
                base.defensive_targets = {
                    UnitTypeId.SPORECRAWLER: 1,
                }

    def morph_overlords(self):
        if 200 <= self.supply_cap:
            return
        supply_pending = sum(
            provided * self.count(unit, include_actual=False)
            for unit, provided in SUPPLY_PROVIDED.items()
        )
        if 200 <= self.supply_cap + supply_pending:
            return
        supply_buffer = 3
        supply_buffer += 3 * self.townhalls.amount
        supply_buffer += 3 * len(self.unit_manager.inject_queens)
        # supply_buffer += self.larva.amount
        if self.supply_left + supply_pending < supply_buffer:
            self.add_macro_plan(MacroPlan(UnitTypeId.OVERLORD, priority=1))

    def expand(self):
        
        worker_max = self.get_max_harvester()
        saturation = self.count(UnitTypeId.DRONE, include_planned=False) / max(1, worker_max)
        saturation = self.bases.harvester_count / max(1, self.bases.harvester_target)
        priority = 2 * (saturation - 0.9)

        if saturation < 2/3:
            return
        
        if not self.count(UnitTypeId.HATCHERY, include_actual=False):
            if any(self.planned_by_type[UnitTypeId.HATCHERY]):
                for plan in self.planned_by_type[UnitTypeId.HATCHERY]:
                    plan.max_distance = 0
                    if plan.priority == BUILD_ORDER_PRIORITY:
                        pass
                    else:
                        plan.priority = priority
            else:
                plan = MacroPlan(UnitTypeId.HATCHERY)
                plan.priority = priority
                plan.max_distance = 0
                self.add_macro_plan(plan)