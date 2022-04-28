

from __future__ import annotations
from re import I
from typing import DefaultDict, Optional, Set, Union, Iterable, Tuple, List, TYPE_CHECKING
from enum import Enum
import numpy as np
import traceback
import random
import logging
from sc2.constants import SPEED_INCREASE_ON_CREEP_DICT

from sc2.position import Point2
from sc2.unit import Unit
from sc2.unit_command import UnitCommand
from sc2.data import Target, race_worker
from abc import ABC, abstractmethod

from src.simulation.unit import SimulationUnit, SimulationUnitWithTarget
from src.units.army import Army
from src.units.changeling import Changeling
from src.units.creep_tumor import CreepTumor
from src.units.extractor import Extractor
from src.units.overlord import Overlord
from src.units.unit import AIUnit
from src.units.queen import Queen
from src.units.worker import Worker
from ..units.extractor import Extractor
from ..units.structure import Structure

from ..behaviors.changeling_scout import SpawnChangelingBehavior
from ..behaviors.burrow import BurrowBehavior
from .dodge import DodgeBehavior
from .combat import CombatBehavior
from .bile import BileBehavior
from ..behaviors.search import SearchBehavior
from .scout import ScoutBehavior
from ..simulation.simulation import Simulation
from ..behaviors.transfuse import TransfuseBehavior
from ..behaviors.survive import SurviveBehavior
from .macro import MacroBehavior
from ..modules.creep import CreepBehavior
from .drop import DropBehavior
from ..behaviors.inject import InjectBehavior
from ..behaviors.gather import GatherBehavior
from ..behaviors.extractor_trick import ExtractorTrickBehavior
from .scout import DetectBehavior
from ..utils import *
from ..constants import *
from ..behaviors.behavior import Behavior
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
    # UnitTypeId.CREEPTUMORBURROWED,
    # UnitTypeId.CREEPTUMORQUEEN,
}

class UnitManager(AIModule):

    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)
        self.inject_queens: Dict[int, int] = dict()
        self.drafted_civilians: Set[int] = set()
        self.enemy_priorities: Dict[int, float] = dict()
        self.behaviors: Dict[int, AIUnit] = dict()
        self.targets: Dict[int, Unit] = dict()
        self.attack_paths: Dict[int, List[Point2]] = dict()
        self.retreat_paths: Dict[int, List[Point2]] = dict()
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

    def add_unit(self, unit: Unit) -> None:
        self.behaviors[unit.tag] = self.create_behavior(unit)

    def remove_unit(self, unit: Unit) -> None:
        del self.behaviors[unit.tag]

    def create_behavior(self, unit: Unit) -> AIUnit:
        
        if unit.type_id in CHANGELINGS:
            return Changeling(self.ai)
        elif unit.is_vespene_geyser:
            return Extractor(self.ai, unit.tag)
        elif unit.type_id in { UnitTypeId.CREEPTUMOR, UnitTypeId.CREEPTUMORBURROWED, UnitTypeId.CREEPTUMORQUEEN }:
            return CreepTumor(self.ai, unit.tag)
        elif unit.type_id == UnitTypeId.LARVA:
            return Structure(self.ai, unit.tag)
        elif unit.type_id in WORKERS:
            return Worker(self.ai, unit.tag)
        elif unit.type_id == UnitTypeId.OVERLORD:
            return Overlord(self.ai, unit.tag)
        elif unit.type_id == UnitTypeId.QUEEN:
            return Queen(self.ai, unit.tag)
        elif unit.is_structure:
            return Structure(self.ai, unit.tag)
        else:
            return Army(self.ai, unit.tag)

    def draft_civilians(self) -> None:

        self.drafted_civilians.intersection_update(self.ai.unit_by_tag.keys())
        
        if (
            0 == self.ai.count(UnitTypeId.SPAWNINGPOOL, include_pending=False, include_planned=False)
            and 2/3 < self.ai.combat.threat_level
        ):
            if worker := self.ai.resource_manager.bases.try_remove_any():
                self.drafted_civilians.add(worker)
        elif self.ai.combat.threat_level < 1/2:
            if self.drafted_civilians:
                worker = min(self.drafted_civilians, key = lambda tag : self.ai.unit_by_tag[tag].shield_health_percentage, default = None)
                self.drafted_civilians.remove(worker)
                self.ai.resource_manager.bases.try_add(worker)

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
            enemy_map = self.ai.combat.enemy_vs_air_map
        else:
            enemy_map = self.ai.combat.enemy_vs_ground_map

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
        inject_queen_count = min(math.ceil((1 - self.ai.combat.threat_level) * inject_queen_max), self.ai.townhalls.amount)
        inject_queens = queens[0:inject_queen_count]

        bases = [
            b
            for b in self.ai.resource_manager.bases
            if b.position in self.ai.townhall_by_position
        ]
        self.inject_queens.clear()
        for queen, base in zip(inject_queens, bases):
            townhall = self.ai.townhall_by_position[base.position]
            self.inject_queens[queen.tag] = townhall.tag

        for unit in self.ai.all_own_units:

            if unit.type_id in IGNORED_UNIT_TYPES:
                continue

            if not unit.is_ready:
                continue

            # behavior = self.behaviors.get(unit.tag)
            # if not behavior:
            #     behavior = self.behaviors[unit.tag] = self.create_behavior(unit)
            behavior = self.behaviors[unit.tag]
            behavior.on_step()