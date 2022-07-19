from __future__ import annotations

from typing import DefaultDict, List, TYPE_CHECKING, Optional, Dict, Iterable
from collections import defaultdict

import numpy as np
from sc2.data import race_townhalls
from sc2.unit import Unit, UnitTypeId

from scipy.spatial import cKDTree

from ..units.army import Army
from ..units.changeling import Changeling
from ..units.creep_tumor import CreepTumor
from ..units.overlord import Overlord
from ..units.queen import Queen
from ..units.unit import AIUnit, CommandableUnit, IdleBehavior
from ..units.worker import Worker
from .macro import MacroId
from .module import AIModule
from ..constants import WORKERS, CHANGELINGS, ITEM_BY_ABILITY
from ..units.extractor import Extractor
from ..units.structure import Larva, Structure

if TYPE_CHECKING:
    from ..ai_base import AIBase

IGNORED_UNIT_TYPES = {
    UnitTypeId.BROODLING,
    UnitTypeId.LOCUSTMP,
    UnitTypeId.LOCUSTMPFLYING,
}


class UnitManager(AIModule):

    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)

        self.units: Dict[int, CommandableUnit] = dict()
        self.enemies: Dict[int, Unit] = dict()

        self.actual_by_type: DefaultDict[MacroId, List[CommandableUnit]] = defaultdict(list)
        self.pending_by_type: DefaultDict[MacroId, List[CommandableUnit]] = defaultdict(list)

    @property
    def townhalls(self) -> Iterable[Structure]:
        return (
            townhall
            for townhall_type in race_townhalls[self.ai.race]
            for townhall in self.actual_by_type[townhall_type]
            if isinstance(townhall, Structure)
        )

    def update_tables(self):

        self.actual_by_type.clear()
        self.pending_by_type.clear()

        for behavior in self.units.values():
            self.add_unit_to_tables(behavior)

        for upgrade in self.ai.state.upgrades:
            self.actual_by_type[upgrade] = [None]

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
            return None
        else:
            return None

    def try_remove_unit(self, tag: int) -> bool:
        return self.units.pop(tag, None) is not None

    def create_unit(self, unit: Unit) -> CommandableUnit:

        if unit.type_id in IGNORED_UNIT_TYPES:
            return IdleBehavior(self.ai, unit)
        if unit.type_id in CHANGELINGS:
            return Changeling(self.ai, unit)
        elif unit.type_id in { UnitTypeId.EXTRACTOR, UnitTypeId.EXTRACTORRICH }:
            return Extractor(self.ai, unit)
        elif unit.type_id in {
            UnitTypeId.CREEPTUMOR,
            UnitTypeId.CREEPTUMORBURROWED,
            UnitTypeId.CREEPTUMORQUEEN
        }:
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

        for tag, enemy in self.enemies.copy().items():
            if self.ai.is_visible(enemy.position):
                del self.enemies[tag]
        self.enemies.update(
            (unit.tag, unit)
            for unit in self.ai.all_enemy_units
            if not unit.is_snapshot
        )

    async def on_step(self) -> None:
        self.update_tags()
        self.update_tables()
        for unit in self.units.values():
            unit.on_step()

        all_units = [
            *self.ai.all_own_units,
            *self.ai.all_enemy_units,
        ]
        all_units_by_positon = {
            unit.position: unit
            for unit in all_units
        }
        all_unit_positions = np.array(list(all_units_by_positon.keys()))
        self.kd_tree = cKDTree(all_unit_positions)
        return