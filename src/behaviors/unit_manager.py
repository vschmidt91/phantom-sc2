

from __future__ import annotations
from typing import DefaultDict, Optional, Set, Union, Iterable, Tuple, TYPE_CHECKING
from enum import Enum
import numpy as np
import random
from sc2.constants import SPEED_INCREASE_ON_CREEP_DICT

from sc2.position import Point2
from sc2.unit import Unit
from sc2.unit_command import UnitCommand
from sc2.data import race_worker
from abc import ABC, abstractmethod

from .changeling_scout import ChangelingSpawnBehavior
from .burrow import BurrowBehavior
from .dodge import DodgeBehavior
from .fight import FightBehavior
from .launch_corrosive_biles import LaunchCorrosiveBilesBehavior
from .search import SearchBehavior
from .scout_manager import ScoutBehavior
from .transfuse import TransfuseBehavior
from .survive import SurviveBehavior
from .inject import InjectBehavior
from .gather import GatherBehavior
from .spread_creep import SpreadCreepBehavior
from .block_manager import DetectBehavior
from ..utils import *
from ..constants import *
from .behavior import Behavior, BehaviorResult, LambdaBehavior, BehaviorSequence, BehaviorSelector, SwitchBehavior, UnitBehavior, LambdaBehavior
from ..ai_component import AIComponent
if TYPE_CHECKING:
    from ..ai_base import AIBase

IGNORED_UNIT_TYPES = {
    UnitTypeId.LARVA,
    UnitTypeId.EGG,
    UnitTypeId.BROODLING,
    UnitTypeId.LOCUSTMP,
    UnitTypeId.LOCUSTMPFLYING,
}

class UnitManager(Behavior):

    def __init__(self, ai: AIBase):
        super().__init__()
        self.ai: AIBase = ai
        self.creep_queens: Set[int] = set()
        self.inject_queens: Dict[int, int] = dict()
        self.drafted_civilians: Set[int] = set()
        self.creep_coverage: float = 0.0
        self.enemy_priorities: Dict[int, float] = dict()
        self.behaviors: Dict[int, UnitBehavior] = dict()

    def is_civilian(self, unit: Unit) -> bool:
        if unit.tag in self.drafted_civilians:
            return False
        elif unit.type_id in CIVILIANS:
            return True
        elif unit.is_structure:
            return True
        else:
            return False

    def create_behavior(self, unit: Unit) -> Behavior:
        def select() -> str:
            if unit.type_id in {
                UnitTypeId.CREEPTUMOR,
                UnitTypeId.CREEPTUMORBURROWED,
                UnitTypeId.CREEPTUMORQUEEN,
            }:
                return 'creep'
            elif unit.type_id in {
                UnitTypeId.QUEEN,
                UnitTypeId.QUEENBURROWED
            }:
                return 'queen'
            elif unit.type_id in {
                UnitTypeId.OVERLORD,
                UnitTypeId.OVERLORDTRANSPORT,
            }:
                return 'overlord'
            elif unit.type_id in {
                UnitTypeId.OVERSEER,
                UnitTypeId.OVERSEERSIEGEMODE
            }:
                return 'overseer'
            elif unit.type_id in CHANGELINGS:
                return 'changeling'
            elif unit.type_id == race_worker[self.ai.race]:
                return 'worker'
            else:
                return 'army'
        behaviors = {
            'creep': SpreadCreepBehavior(self.ai, unit.tag),
            'queen': BehaviorSequence([
                    DodgeBehavior(self.ai, unit.tag),
                    SpreadCreepBehavior(self.ai, unit.tag),
                    InjectBehavior(self.ai, unit.tag),
                    TransfuseBehavior(self.ai, unit.tag),
                    FightBehavior(self.ai, unit.tag),
                    SearchBehavior(self.ai, unit.tag),
                ]),
            'overlord': BehaviorSequence([
                    DodgeBehavior(self.ai, unit.tag),
                    SurviveBehavior(self.ai, unit.tag),
                    ScoutBehavior(self.ai, unit.tag),
                ]),
            'changeling': SearchBehavior(self.ai, unit.tag),
            'overseer': BehaviorSequence([
                    DodgeBehavior(self.ai, unit.tag),
                    SurviveBehavior(self.ai, unit.tag),
                    ChangelingSpawnBehavior(self.ai, unit.tag),
                    DetectBehavior(self.ai, unit.tag),
                    FightBehavior(self.ai, unit.tag),
                    SearchBehavior(self.ai, unit.tag),
                ]),
            'worker': BehaviorSequence([
                    DodgeBehavior(self.ai, unit.tag),
                    SurviveBehavior(self.ai, unit.tag),
                    GatherBehavior(self.ai, unit.tag),
                ]),
            'army': BehaviorSequence([
                    DodgeBehavior(self.ai, unit.tag),
                    BurrowBehavior(self.ai, unit.tag),
                    LaunchCorrosiveBilesBehavior(self.ai, unit.tag),
                    FightBehavior(self.ai, unit.tag),
                    SearchBehavior(self.ai, unit.tag),
                ]),
        }
        return SwitchBehavior(select, behaviors)
        
        return BehaviorSequence([
            DodgeBehavior(self.ai, unit.tag),
            SpreadCreepBehavior(self.ai, unit.tag),
            BehaviorSelector([
                LambdaBehavior(lambda : BehaviorResult.SUCCESS if self.is_civilian(unit) else BehaviorResult.FAILURE),
                
            ]),
            BehaviorSelector([
                LambdaBehavior(lambda : BehaviorResult.FAILURE if self.is_civilian(unit) else BehaviorResult.SUCCESS),
                
            ])
        ])

    def draft_civilians(self):

        self.drafted_civilians = {
            u for u in self.drafted_civilians
            if u in self.ai.unit_by_tag
        }
        
        if (
            2/3 < self.ai.threat_level
            and self.ai.time < 3 * 60
        ):
            worker = self.ai.bases.try_remove_any()
            if worker:
                self.drafted_civilians.add(worker)
        elif self.ai.threat_level < 1/3:
            if self.drafted_civilians:
                worker = self.drafted_civilians.pop()
                if not self.ai.bases.try_add(worker):
                    self.drafted_civilians.add(worker)

    def target_priority_apriori(self, target: Unit) -> float:
        if target.is_hallucination:
            return 0
        if target.type_id in CHANGELINGS:
            return 0
        priority = 1e3
        priority /= 150 + target.position.distance_to(self.ai.start_location)
        priority /= 3 if target.is_structure else 1
        if target.is_enemy:
            priority /= 100 + target.shield + target.health
        else:
            priority /= 200
        priority *= 3 if target.type_id in WORKERS else 1
        priority /= 10 if target.type_id in CIVILIANS else 1
        return priority

    def execute(self) -> BehaviorResult:

        self.creep_coverage = np.sum(self.ai.state.creep.data_numpy) / self.ai.creep_tile_count

        self.enemy_priorities = {
            e.tag: self.target_priority_apriori(e)
            for e in self.ai.enumerate_enemies()
        }

        self.draft_civilians()

        queens = sorted(
            self.ai.actual_by_type[UnitTypeId.QUEEN],
            key = lambda q : q.tag
            # key = lambda q : self.ai.distance_map[q.position.rounded]
        )

        inject_queen_count = min(3, len(queens), self.ai.townhalls.amount)
        creep_queen_count = 1 if max(inject_queen_count, 2) < len(queens) else 0

        inject_queens = queens[0:inject_queen_count]
        creep_queens = queens[inject_queen_count:inject_queen_count+creep_queen_count]

        self.creep_queens = { q.tag for q in creep_queens }

        bases = [
            b
            for b in self.ai.bases
            if b.position in self.ai.townhall_by_position
        ]
        self.inject_queens.clear()
        for queen, base in zip(inject_queens, bases):
            townhall = self.ai.townhall_by_position[base.position]
            self.inject_queens[queen.tag] = townhall.tag

        # self.army_manager.unit_tags.clear()
        # for unit in self.ai.units:
            
        #     if unit.type_id == UnitTypeId.QUEEN:
        #         exclude_abilities = {
        #             AbilityId.BUILD_CREEPTUMOR_QUEEN,
        #             AbilityId.EFFECT_INJECTLARVA,
        #             AbilityId.TRANSFUSION_TRANSFUSION,
        #         }
        #         order_abilities = {
        #             o.ability.exact_id
        #             for o in unit.orders
        #         }
        #         if unit in creep_queens:
        #             pass
        #         elif unit in inject_queens:
        #             pass
        #         elif order_abilities.intersection(exclude_abilities):
        #             pass
        #         else:
        #             self.army_manager.unit_tags.add(unit.tag)
        #     elif unit.type_id == UnitTypeId.OVERSEER:
        #         if unit.tag in self.ai.blocked_base_detectors.values():
        #             pass
        #         else:
        #             self.army_manager.unit_tags.add(unit.tag)
        #     elif unit.type_id not in CIVILIANS:
        #         self.army_manager.unit_tags.add(unit.tag)
        #     elif unit.tag in self.drafted_civilians:
        #         self.army_manager.unit_tags.add(unit.tag)
        #     else:
        #         pass

        units = list()
        units.extend(u for u in self.ai.units if u.type_id not in IGNORED_UNIT_TYPES)
        units.extend(self.ai.tumor_front)


        for unit in units:
            behavior = self.behaviors.get(unit.tag)
            if not behavior:
                behavior = self.create_behavior(unit)
                self.behaviors[unit.tag] = behavior
            result = behavior.execute()
            # if result is not BehaviorResult.ONGOING:
            #     print('error')
            #     behavior.execute()

        tags = { u.tag for u in units }
        removed_tags = {
            tag for tag in self.behaviors.keys()
            if tag not in tags
        }
        for tag in removed_tags:
            del self.behaviors[tag]

        return BehaviorResult.ONGOING