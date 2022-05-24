

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
from sc2.data import Target, race_worker, Alliance
from abc import ABC, abstractmethod
from src.resources.resource_unit import ResourceUnit

from src.simulation.unit import SimulationUnit, SimulationUnitWithTarget
from src.units.army import Army
from src.units.changeling import Changeling
from src.units.creep_tumor import CreepTumor
from src.units.extractor import Extractor
from src.units.overlord import Overlord
from src.units.unit import AIUnit, CommandableUnit, EnemyUnit, IdleBehavior
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
from .macro import MacroBehavior, MacroId
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
        # self.neutrals: Dict[int, AIUnit] = dict()

        self.actual_by_type: DefaultDict[MacroId, List[CommandableUnit]] = defaultdict(list)
        self.pending_by_type: DefaultDict[MacroId, List[CommandableUnit]] = defaultdict(list)

    @property
    def townhalls(self) -> Iterable[Structure]:
        return (
            townhall
            for townhall_type in race_townhalls[self.ai.race]
            for townhall in self.actual_by_type[townhall_type]
        )

    def update_tables(self):
        
        self.actual_by_type.clear()
        self.pending_by_type.clear()
        
        for behavior in self.units.values():
            self.add_unit_to_tables(behavior)
            
        self.actual_by_type.update((upgrade, [None]) for upgrade in self.ai.state.upgrades)

    def add_unit_to_tables(self, behavior: CommandableUnit) -> None:
        if not behavior.unit:
            pass
        elif behavior.unit.is_ready:
            self.actual_by_type[behavior.unit.type_id].append(behavior)
            for order in behavior.unit.orders:
                if item := ITEM_BY_ABILITY.get(order.ability.exact_id):
                    self.pending_by_type[item].append(behavior)
        else:
            self.pending_by_type[behavior.unit.type_id].append(behavior)

    def add_unit(self, unit: Unit) -> Optional[AIUnit]:
        if unit.type_id in IGNORED_UNIT_TYPES:
            return None
        elif unit.is_mine:
            behavior = self.create_unit(unit)
            self.add_unit_to_tables(behavior)
            self.units[unit.tag] = behavior
            return behavior
        elif unit.is_enemy:
            behavior = EnemyUnit(self.ai, unit.tag)
            self.enemies[unit.tag] = behavior
            return behavior
        else:
            return None
        # elif unit.is_mineral_field or unit.is_vespene_geyser:
        #     behavior = ResourceUnit(self.ai, unit.position)
        #     self.resources[unit.position] = behavior
        # else:
        #     behavior = AIUnit(self.ai, unit)
        #     self.neutrals[unit.tag] = behavior

    def try_remove_unit(self, tag: int) -> bool:
        return any((
            self.units.pop(tag, None),
            self.enemies.pop(tag, None),
            # self.neutrals.pop(tag, None),
        ))

    def create_unit(self, unit: Unit) -> CommandableUnit:
        
        if unit.type_id in IGNORED_UNIT_TYPES:
            return IdleBehavior(self.ai, unit)
        if unit.type_id in CHANGELINGS:
            return Changeling(self.ai, unit)
        elif unit.type_id in { UnitTypeId.EXTRACTOR, UnitTypeId.EXTRACTORRICH }:
            return Extractor(self.ai, unit)
        elif unit.type_id in { UnitTypeId.CREEPTUMOR, UnitTypeId.CREEPTUMORBURROWED, UnitTypeId.CREEPTUMORQUEEN }:
            return CreepTumor(self.ai, unit)
        elif unit.type_id == UnitTypeId.LARVA:
            return Larva(self.ai, unit)
        elif unit.type_id in WORKERS:
            return Worker(self.ai, unit)
        elif unit.type_id == UnitTypeId.OVERLORD:
            return Overlord(self.ai, unit)
        elif unit.type_id == UnitTypeId.QUEEN:
            return Queen(self.ai, unit)
        elif self.ai.techtree.units[unit.type_id].is_structure:
            return Structure(self.ai, unit)
        else:
            return Army(self.ai, unit)

    def update_tags(self) -> None:

        unit_by_tag = {
            unit.tag: unit
            for unit in self.ai.all_own_units
        }
        for tag, unit in self.units.items():
            unit.unit = unit_by_tag.get(tag)
            
        # neutral_by_tag = {
        #     unit.tag: unit
        #     for unit in self.ai.all_units
        #     if unit.alliance == Alliance.Neutral
        # }
        # for tag, unit in self.neutrals.items():
        #     unit.unit = neutral_by_tag.get(tag)

        enemy_by_tag = {
            unit.tag: unit
            for unit in self.ai.all_enemy_units
        }
        for tag, unit in list(self.enemies.items()):
            if new_unit := enemy_by_tag.get(tag):
                unit.unit = new_unit
                unit.is_snapshot = False
            elif self.ai.is_visible(unit.unit.position):
                del self.enemies[tag]
            else:
                unit.is_snapshot = True

    async def on_step(self) -> None:
        self.update_tags()
        self.update_tables()
        for unit in self.units.values():
            unit.on_step()

    def ball_query(self, position: Point2, radius: float) -> Iterable[CommandableUnit]:
        query = self.unit_tree.query_ball_point(position, radius)
        return (self.unit_list[i] for i in query)