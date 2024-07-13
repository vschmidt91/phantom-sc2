from __future__ import annotations

import logging
from collections import defaultdict
from itertools import chain
from typing import TYPE_CHECKING, DefaultDict, Dict, Iterable, List, Optional

import numpy as np
import skimage.draw
from sc2.data import race_townhalls
from sc2.position import Point2
from sc2.unit import Unit, UnitTypeId
from scipy.spatial import cKDTree

from ..constants import CHANGELINGS, ITEM_BY_ABILITY, WORKERS
from ..units.army import Army
from ..units.changeling import Changeling
from ..units.creep_tumor import CreepTumor
from ..units.extractor import Extractor
from ..units.overlord import Overlord
from ..units.queen import Queen
from ..units.structure import Larva, Structure
from ..units.unit import AIUnit, IdleBehavior
from ..units.worker import Worker
from .macro import MacroId
from .module import AIModule

if TYPE_CHECKING:
    from ..ai_base import AIBase

IGNORED_UNIT_TYPES = {
    UnitTypeId.BROODLING,
    UnitTypeId.LOCUSTMP,
    UnitTypeId.LOCUSTMPFLYING,
}

# VISIBILITY_OFFSETS = np.array([
#     [0, 0],
#     [-1, 0],
#     [+1, 0],
#     [0, -1],
#     [0, +1],
# ])


class UnitManager(AIModule):
    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)

        self.units: Dict[int, AIUnit] = dict()

        self.actual_by_type: DefaultDict[MacroId, List[AIUnit]] = defaultdict(list)
        self.pending_by_type: DefaultDict[MacroId, List[AIUnit]] = defaultdict(list)

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

    def add_unit_to_tables(self, behavior: AIUnit) -> None:
        if behavior.unit.is_ready:
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
        if self.units.pop(tag, None):
            return True
        else:
            return False

    def create_unit(self, unit: Unit) -> AIUnit:
        if unit.type_id in IGNORED_UNIT_TYPES:
            return IdleBehavior(self.ai, unit)
        if unit.type_id in CHANGELINGS:
            return Changeling(self.ai, unit)
        elif unit.type_id in {UnitTypeId.EXTRACTOR, UnitTypeId.EXTRACTORRICH}:
            return Extractor(self.ai, unit)
        elif unit.type_id in {UnitTypeId.CREEPTUMOR, UnitTypeId.CREEPTUMORBURROWED, UnitTypeId.CREEPTUMORQUEEN}:
            return CreepTumor(self.ai, unit)
        elif unit.type_id == UnitTypeId.LARVA:
            return Larva(self.ai, unit)
        elif unit.type_id in WORKERS:
            return Worker(self.ai, unit)
        elif unit.type_id in {
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORDTRANSPORT,
        }:
            return Overlord(self.ai, unit)
        elif unit.type_id == UnitTypeId.QUEEN:
            return Queen(self.ai, unit)
        elif unit.is_structure:
            return Structure(self.ai, unit)
        else:
            return Army(self.ai, unit)

    def update_tags(self) -> None:
        unit_by_tag = {u.tag: u for u in self.ai.all_own_units}
        for tag, unit in self.units.items():
            unit.unit = unit_by_tag.get(tag) or unit.unit

    async def on_step(self) -> None:
        self.update_tags()
        self.update_tables()

        for unit in self.units.values():
            command = unit.get_command()
            if not command:
                continue
            # if any(self.ai.order_matches_command(o, command) for o in command.unit.orders):
            #     continue
            result = self.ai.do(command, subtract_cost=False, subtract_supply=False)
            if not result:
                logging.error("command failed: %s", command)

        self.unit_by_position = {u.position: u for u in chain(self.ai.all_own_units, self.ai.all_enemy_units)}
        self.unit_positions = list(self.unit_by_position.keys())
        self.unit_tree = cKDTree(np.array(self.unit_positions))
        return

    def units_in_circle(self, position: Point2, radius: float) -> Iterable[Unit]:
        result = self.unit_tree.query_ball_point(position, radius)
        return (self.unit_by_position[self.unit_positions[i]] for i in result)
