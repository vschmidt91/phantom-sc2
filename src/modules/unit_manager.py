

from __future__ import annotations
from typing import DefaultDict, Optional, Set, Union, Iterable, Tuple, List, TYPE_CHECKING
from enum import Enum
import numpy as np
import traceback
import random
from sc2.constants import SPEED_INCREASE_ON_CREEP_DICT

from sc2.position import Point2
from sc2.unit import Unit
from sc2.unit_command import UnitCommand
from sc2.data import race_worker
from abc import ABC, abstractmethod

from ..behaviors.changeling_scout import ChangelingSpawnBehavior
from ..behaviors.burrow import BurrowBehavior
from ..behaviors.dodge import DodgeBehavior
from ..behaviors.fight import FightBehavior
from ..behaviors.launch_corrosive_biles import LaunchCorrosiveBilesBehavior
from ..behaviors.search import SearchBehavior
from .scout_manager import ScoutBehavior
from ..behaviors.transfuse import TransfuseBehavior
from ..behaviors.survive import SurviveBehavior
from ..behaviors.macro import MacroBehavior
from .drop_manager import DropBehavior
from ..behaviors.inject import InjectBehavior
from ..behaviors.gather import GatherBehavior
from ..behaviors.extractor_trick import ExtractorTrickBehavior
from .scout_manager import DetectBehavior
from ..utils import *
from ..constants import *
from ..behaviors.behavior import Behavior, BehaviorResult, LambdaBehavior, BehaviorSequence, BehaviorSelector, SwitchBehavior, UnitBehavior, LambdaBehavior
from .module import AIModule
if TYPE_CHECKING:
    from ..ai_base import AIBase

IGNORED_UNIT_TYPES = {
    # UnitTypeId.LARVA,
    UnitTypeId.EGG,
    UnitTypeId.BROODLING,
    UnitTypeId.LOCUSTMP,
    UnitTypeId.LOCUSTMPFLYING,
    UnitTypeId.CREEPTUMOR,
    UnitTypeId.CREEPTUMORBURROWED,
    UnitTypeId.CREEPTUMORQUEEN,
}

class UnitManager(AIModule):

    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)
        self.inject_queens: Dict[int, int] = dict()
        self.drafted_civilians: Set[int] = set()
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

    def create_behavior(self, unit_tag: int) -> Behavior:
        def selector(unit: Unit) -> str:
            if unit.type_id == UnitTypeId.EXTRACTOR:
                return 'extractor'
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
            elif unit.type_id in {
                UnitTypeId.SCV,
                UnitTypeId.DRONE,
                UnitTypeId.DRONEBURROWED,
                UnitTypeId.PROBE,
                UnitTypeId.MULE,
            }:
                if unit.tag in self.drafted_civilians:
                    return 'army'
                elif 1 < self.ai.enemy_vs_ground_map[unit.position.rounded] < np.inf:
                    return 'army'
                else:
                    return 'worker'
            elif unit.is_structure or unit.type_id == UnitTypeId.LARVA:
                return 'structure_or_larva'
            else:
                return 'army'
        behaviors = {
            'extractor': ExtractorTrickBehavior(self.ai, unit_tag),
            'queen': BehaviorSequence([
                    DodgeBehavior(self.ai, unit_tag),
                    InjectBehavior(self.ai, unit_tag),
                    LambdaBehavior(lambda:self.ai.creep.spread(self.ai.unit_by_tag[unit_tag])),
                    # SpreadCreepBehavior(self.ai, unit_tag),
                    TransfuseBehavior(self.ai, unit_tag),
                    FightBehavior(self.ai, unit_tag),
                    SearchBehavior(self.ai, unit_tag),
                ]),
            'overlord': BehaviorSequence([
                    MacroBehavior(self.ai, unit_tag),
                    DodgeBehavior(self.ai, unit_tag),
                    DropBehavior(self.ai, unit_tag),
                    SurviveBehavior(self.ai, unit_tag),
                    ScoutBehavior(self.ai, unit_tag),
                ]),
            'changeling': SearchBehavior(self.ai, unit_tag),
            'overseer': BehaviorSequence([
                    DodgeBehavior(self.ai, unit_tag),
                    ChangelingSpawnBehavior(self.ai, unit_tag),
                    DetectBehavior(self.ai, unit_tag),
                    FightBehavior(self.ai, unit_tag),
                    SearchBehavior(self.ai, unit_tag),
                ]),
            'structure_or_larva': MacroBehavior(self.ai, unit_tag),
            'worker': BehaviorSequence([
                    MacroBehavior(self.ai, unit_tag),
                    DodgeBehavior(self.ai, unit_tag),
                    SurviveBehavior(self.ai, unit_tag),
                    GatherBehavior(self.ai, unit_tag),
                    FightBehavior(self.ai, unit_tag),
                ]),
            'army': BehaviorSequence([
                    MacroBehavior(self.ai, unit_tag),
                    DodgeBehavior(self.ai, unit_tag),
                    BurrowBehavior(self.ai, unit_tag),
                    LaunchCorrosiveBilesBehavior(self.ai, unit_tag),
                    DropBehavior(self.ai, unit_tag),
                    # HideBehavior(self.ai, unit_tag),
                    FightBehavior(self.ai, unit_tag),
                    SearchBehavior(self.ai, unit_tag),
                ]),
        }
        return SwitchBehavior(self.ai, unit_tag, selector, behaviors)

    def draft_civilians(self) -> None:

        self.drafted_civilians.intersection_update(self.ai.unit_by_tag.keys())
        
        if (
            2/3 < self.ai.threat_level
            and self.ai.time < 3 * 60
        ):
            if worker := self.ai.bases.try_remove_any():
                self.drafted_civilians.add(worker)
        elif self.ai.threat_level < 1/2:
            if self.drafted_civilians:
                worker = min(self.drafted_civilians, key = lambda tag : self.ai.unit_by_tag[tag].shield_health_percentage, default = None)
                self.drafted_civilians.remove(worker)

    def target_priority_apriori(self, target: Unit) -> float:
        if target.is_hallucination:
            return 0
        if target.type_id in CHANGELINGS:
            return 0
        priority = 1e8
        priority /= 150 + target.position.distance_to(self.ai.start_location)
        priority /= 3 if target.is_structure else 1
        if target.is_enemy:
            priority /= 100 + target.shield + target.health
        else:
            priority /= 500
        priority *= 3 if target.type_id in WORKERS else 1
        priority /= 10 if target.type_id in CIVILIANS else 1
        return priority

    async def on_step(self) -> None:

        self.enemy_priorities = {
            e.tag: self.target_priority_apriori(e)
            for e in self.ai.enumerate_enemies()
        }

        # self.draft_civilians()

        queens = sorted(
            self.ai.actual_by_type[UnitTypeId.QUEEN],
            key = lambda q : q.tag
        )

        inject_queen_max = min(5, len(queens))
        inject_queen_count = min(math.ceil((1 - self.ai.threat_level) * inject_queen_max), self.ai.townhalls.amount)
        inject_queens = queens[0:inject_queen_count]

        bases = [
            b
            for b in self.ai.bases
            if b.position in self.ai.townhall_by_position
        ]
        self.inject_queens.clear()
        for queen, base in zip(inject_queens, bases):
            townhall = self.ai.townhall_by_position[base.position]
            self.inject_queens[queen.tag] = townhall.tag

        tags: List[int] = list()
        tags.extend(u.tag for u in self.ai.all_own_units if u.type_id not in IGNORED_UNIT_TYPES)
        # tags.extend(self.ai.creep.tumor_front_tags)

        for tag in tags:
            behavior = self.behaviors.get(tag)
            if not behavior:
                behavior = self.create_behavior(tag)
                self.behaviors[tag] = behavior
            result = behavior.execute()
            if result == BehaviorResult.FAILURE:
                print('behavior failure')
                behavior.execute()

        removed_tags = {
            tag for tag in self.behaviors.keys()
            if tag not in tags
        }
        for tag in removed_tags:
            del self.behaviors[tag]