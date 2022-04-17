

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
from src.modules.creep import SpreadCreep

from src.simulation.unit import SimulationUnit, SimulationUnitWithTarget

from ..behaviors.changeling_scout import SpawnChangeling
from ..behaviors.burrow import BurrowBehavior
from ..behaviors.dodge import DodgeBehavior
from ..behaviors.fight import FightBehavior
from ..behaviors.launch_corrosive_biles import LaunchCorrosiveBilesBehavior
from ..behaviors.search import SearchBehavior
from .scout_manager import ScoutBehavior
from ..simulation.simulation import Simulation
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
from ..behaviors.behavior import Behavior, LambdaBehavior, BehaviorSequence, SwitchBehavior
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
        self.behaviors: Dict[int, Behavior] = dict()
        self.targets: Dict[int, Unit] = dict()
        self.attack_paths: Dict[int, List[Point2]] = dict()
        self.retreat_paths: Dict[int, List[Point2]] = dict()
        self.simulation_map: np.ndarray = np.zeros(self.ai.game_info.map_size)
        self.path_modulus: int = 4

    def is_civilian(self, unit: Unit) -> bool:
        if unit.tag in self.drafted_civilians:
            return False
        elif unit.type_id in CIVILIANS:
            return True
        elif unit.is_structure:
            return True
        else:
            return False

    def add_creep_tumor(self, tumor: Unit) -> None:
        self.behaviors[tumor.tag] = SpreadCreep(self.ai, tumor.tag)

    def create_behavior(self, unit: Unit) -> Behavior:

        if unit.type_id in {
            UnitTypeId.QUEEN,
            UnitTypeId.QUEENBURROWED,
        }:
            return BehaviorSequence([
                DodgeBehavior(self.ai, unit.tag),
                InjectBehavior(self.ai, unit.tag),
                LambdaBehavior(lambda:self.ai.creep.spread(self.ai.unit_by_tag[unit.tag])),
                SpreadCreep(self.ai, unit.tag),
                TransfuseBehavior(self.ai, unit.tag),
                FightBehavior(self.ai, unit.tag),
                SearchBehavior(self.ai, unit.tag),
            ])
        elif unit.type_id in CHANGELINGS:
            return SearchBehavior(self.ai, unit.tag)
        elif unit.type_id == UnitTypeId.EXTRACTOR:
            return ExtractorTrickBehavior(self.ai, unit.tag)
        elif unit.is_structure or unit.type_id == UnitTypeId.LARVA:
            return MacroBehavior(self.ai, unit.tag)

        def selector(unit: Unit) -> str:
            if unit.type_id in {
                UnitTypeId.OVERLORD,
                UnitTypeId.OVERLORDTRANSPORT,
            }:
                return 'overlord'
            elif unit.type_id in {
                UnitTypeId.OVERSEER,
                UnitTypeId.OVERSEERSIEGEMODE
            }:
                return 'overseer'
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
                elif (
                    (last_attacked := self.ai.damage_taken.get(unit.tag))
                    and self.ai.time < last_attacked + 5
                ):
                    return 'army'
                else:
                    return 'worker'
            else:
                return 'army'
        behaviors = {
            'overlord': BehaviorSequence(self.ai, unit.tag, [
                    MacroBehavior(self.ai, unit.tag),
                    DodgeBehavior(self.ai, unit.tag),
                    DropBehavior(self.ai, unit.tag),
                    SurviveBehavior(self.ai, unit.tag),
                    ScoutBehavior(self.ai, unit.tag),
                ]),
            'overseer': BehaviorSequence(self.ai, unit.tag, [
                    DodgeBehavior(self.ai, unit.tag),
                    SpawnChangeling(self.ai, unit.tag),
                    DetectBehavior(self.ai, unit.tag),
                    FightBehavior(self.ai, unit.tag),
                    SearchBehavior(self.ai, unit.tag),
                ]),
            'worker': BehaviorSequence(self.ai, unit.tag, [
                    MacroBehavior(self.ai, unit.tag),
                    DodgeBehavior(self.ai, unit.tag),
                    # SurviveBehavior(self.ai, unit.tag),
                    GatherBehavior(self.ai, unit.tag),
                    FightBehavior(self.ai, unit.tag),
                ]),
            'army': BehaviorSequence(self.ai, unit.tag, [
                    MacroBehavior(self.ai, unit.tag),
                    DodgeBehavior(self.ai, unit.tag),
                    BurrowBehavior(self.ai, unit.tag),
                    LaunchCorrosiveBilesBehavior(self.ai, unit.tag),
                    DropBehavior(self.ai, unit.tag),
                    # HideBehavior(self.ai, unit.tag),
                    FightBehavior(self.ai, unit.tag),
                    SearchBehavior(self.ai, unit.tag),
                ]),
        }
        return SwitchBehavior(self.ai, unit.tag, selector, behaviors)

    def draft_civilians(self) -> None:

        self.drafted_civilians.intersection_update(self.ai.unit_by_tag.keys())
        
        if (
            0 == self.ai.count(UnitTypeId.SPAWNINGPOOL, include_pending=False, include_planned=False)
            and 2/3 < self.ai.threat_level
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

    def target_priority(self, unit: Unit, target: Unit) -> float:
        if not self.ai.can_attack(unit, target) and not unit.is_detector:
            return 0
        priority = self.enemy_priorities[target.tag]
        priority /= 30 + target.position.distance_to(unit.position)
        if unit.is_detector:
            priority *= 10 if target.is_cloaked else 1
            priority *= 10 if not target.is_revealed else 1
        return priority

    def get_path_towards(self, unit: Unit, target: Point2) -> List[Point2]:
        a = self.ai.game_info.playable_area
        target = Point2(np.clip(target, (a.x, a.y), (a.right, a.top)))
        if unit.is_flying:
            enemy_map = self.ai.enemy_vs_air_map
        else:
            enemy_map = self.ai.enemy_vs_ground_map

        path = self.ai.map_analyzer.pathfind(
            start = unit.position,
            goal = target,
            grid = enemy_map,
            large = is_large(unit),
            smoothing = False,
            sensitivity = 1)

        if not path:
            d = unit.distance_to(target)
            return [
                unit.position.towards(target, d)
                for i in np.arange(d)
            ]
        return path

    async def on_step(self) -> None:

        self.enemy_priorities = {
            e.tag: self.target_priority_apriori(e)
            for e in self.ai.enumerate_enemies()
        }

        self.targets = dict()
        for unit in self.ai.army:
            if (unit.tag % self.path_modulus) != (self.ai.iteration % self.path_modulus):
                continue
            target, priority = max(
                ((t, self.target_priority(unit, t))
                for t in self.ai.enumerate_enemies()),
                key = lambda p : p[1],
                default = (None, 0))
            if priority <= 0:
                continue
            self.targets[unit.tag] = target
            self.attack_paths[unit.tag] = self.get_path_towards(unit, target.position)
            self.retreat_paths[unit.tag] = self.get_path_towards(unit, unit.position.towards(target.position, -12))

        queens = sorted(
            self.ai.actual_by_type[UnitTypeId.QUEEN],
            key = lambda q : q.tag
        )

        self.draft_civilians()

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

        commands: List[UnitCommand] = list()

        for unit in self.ai.all_own_units:
            if unit.type_id in IGNORED_UNIT_TYPES:
                continue
            behavior = self.behaviors.get(unit.tag)
            if not behavior:
                behavior = self.create_behavior(unit)
                self.behaviors[unit.tag] = behavior
            if command := behavior.execute():
                if not self.ai.do(command, subtract_cost=True, subtract_supply=True):
                    raise Exception()