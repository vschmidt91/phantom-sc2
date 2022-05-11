

from __future__ import annotations
from re import I
from typing import DefaultDict, Optional, Set, Union, Iterable, Tuple, List, TYPE_CHECKING
from enum import Enum
import numpy as np
import traceback
import random
import logging
from scipy.spatial.kdtree import KDTree

from sc2.constants import SPEED_INCREASE_ON_CREEP_DICT
from sc2.data import race_townhalls
from sc2.position import Point2
from sc2.unit import Unit
from sc2.unit_command import UnitCommand
from sc2.data import Target, race_worker
from abc import ABC, abstractmethod
from src.resources.resource_unit import ResourceUnit

from src.simulation.unit import SimulationUnit, SimulationUnitWithTarget
from src.units.army import Army
from src.units.changeling import Changeling
from src.units.creep_tumor import CreepTumor
from src.units.extractor import Extractor
from src.units.overlord import Overlord
from src.units.unit import AIUnit, CommandableUnit, EnemyUnit, IdleBehavior, UnitByTag
from src.units.queen import Queen
from src.units.worker import Worker
from ..units.extractor import Extractor
from ..units.structure import Larva, Structure

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
from ..utils import *
from ..constants import *
from ..behaviors.behavior import Behavior
from .module import AIModule
if TYPE_CHECKING:
    from ..ai_base import AIBase

IGNORED_UNIT_TYPES = {
    # UnitTypeId.LARVA,
    # UnitTypeId.EGG,
    UnitTypeId.BROODLING,
    UnitTypeId.LOCUSTMP,
    UnitTypeId.LOCUSTMPFLYING,
    # UnitTypeId.CREEPTUMOR,
    # UnitTypeId.CREEPTUMORBURROWED,
    # UnitTypeId.CREEPTUMORQUEEN,
}

class UnitManager(AIModule):

    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)

        self.units: Dict[int, CommandableUnit] = dict()
        self.enemies: Dict[int, EnemyUnit] = dict()
        self.resources: Dict[Point2, ResourceUnit] = dict()
        self.neutrals: Dict[int, UnitByTag] = dict()

        self.resource_by_position: Dict[Point2, Unit] = dict()
        self.structure_by_position: Dict[Point2, Unit] = dict()
        self.unit_by_tag: Dict[int, Unit] = dict()

    def add_unit(self, unit: Unit) -> Optional[AIUnit]:
        if unit.is_mine:
            behavior = self.create_unit(unit.tag, unit.type_id)
            self.units[unit.tag] = behavior
        elif unit.is_enemy:
            behavior = EnemyUnit(self.ai, unit.tag)
            self.enemies[unit.tag] = behavior
        elif unit.is_mineral_field or unit.is_vespene_geyser:
            behavior = ResourceUnit(self.ai, unit.position)
            self.resources[unit.position] = behavior
        else:
            behavior = UnitByTag(self.ai, unit.tag)
            self.neutrals[unit.tag] = behavior
        return behavior

    def try_remove_unit(self, tag: int) -> bool:
        return any((
            self.units.pop(tag, None),
            self.enemies.pop(tag, None),
            self.neutrals.pop(tag, None),
        ))

    def create_unit(self, tag: int, unit_type: UnitTypeId) -> CommandableUnit:
        
        if unit_type in IGNORED_UNIT_TYPES:
            return IdleBehavior(self.ai, tag)
        if unit_type in CHANGELINGS:
            return Changeling(self.ai, tag)
        elif unit_type in { UnitTypeId.EXTRACTOR, UnitTypeId.EXTRACTORRICH }:
            return Extractor(self.ai, tag)
        elif unit_type in { UnitTypeId.CREEPTUMOR, UnitTypeId.CREEPTUMORBURROWED, UnitTypeId.CREEPTUMORQUEEN }:
            return CreepTumor(self.ai, tag)
        elif unit_type == UnitTypeId.LARVA:
            return Larva(self.ai, tag)
        elif unit_type in WORKERS:
            return Worker(self.ai, tag)
        elif unit_type == UnitTypeId.OVERLORD:
            return Overlord(self.ai, tag)
        elif unit_type == UnitTypeId.QUEEN:
            return Queen(self.ai, tag)
        elif self.ai.techtree.units[unit_type].is_structure:
            return Structure(self.ai, tag)
        else:
            return Army(self.ai, tag)

    async def on_step(self) -> None:

        self.unit_by_tag = {
            unit.tag: unit
            for unit in self.ai.all_units
        }

        self.resource_by_position = {
            unit.position: unit
            for unit in self.ai.resources
        }

        self.structure_by_position = {
            structure.position: structure
            for structure in self.ai.structures
        }
        
        self.unit_list = list(self.units.values())
        self.unit_tree = KDTree([
            behavior.unit.position
            for behavior in self.unit_list
            if behavior.unit
        ])

        for unit in self.units.values():
            unit.on_step()

        for enemy in self.enemies.values():
            if enemy.snapshot and self.ai.is_visible(enemy.snapshot.position):
                enemy.snapshot = None

    def ball_query(self, position: Point2, radius: float) -> Iterable[CommandableUnit]:
        query = self.unit_tree.query_ball_point(position, radius)
        return (self.unit_list[i] for i in query)