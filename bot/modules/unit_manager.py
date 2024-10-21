from __future__ import annotations

from collections import defaultdict
from itertools import chain
from typing import TYPE_CHECKING, Iterable

import numpy as np
from sc2.data import race_townhalls
from sc2.position import Point2
from sc2.unit import Unit, UnitTypeId
from sc2.units import Units
from scipy.spatial import cKDTree

from ..constants import CHANGELINGS, IGNORED_UNIT_TYPES, ITEM_BY_ABILITY, WORKERS
from ..units.army import Army
from ..units.changeling import Changeling
from ..units.extractor import Extractor
from ..units.overlord import Overlord
from ..units.queen import Queen
from ..units.unit import AIUnit, IdleBehavior
from ..units.worker import Worker
from .macro import MacroId
from .module import AIModule

if TYPE_CHECKING:
    from ..ai_base import PhantomBot


class UnitManager(AIModule):
    def __init__(self, ai: PhantomBot) -> None:
        super().__init__(ai)
        self.units: dict[int, AIUnit] = dict()
        self.actual_by_type: defaultdict[MacroId, list[AIUnit]] = defaultdict(list)
        self.pending_by_type: defaultdict[MacroId, list[AIUnit]] = defaultdict(list)

    @property
    def townhalls(self) -> Units:
        return self.ai.units(race_townhalls[self.ai.race])

    def update_tables(self):
        self.actual_by_type.clear()
        self.pending_by_type.clear()

        for behavior in self.units.values():
            self.add_unit_to_tables(behavior)

        for upgrade in self.ai.state.upgrades:
            self.actual_by_type[upgrade] = [self.ai.all_units[0]]

    def add_unit_to_tables(self, behavior: AIUnit) -> None:
        if behavior.unit.is_ready:
            self.actual_by_type[behavior.unit.type_id].append(behavior)
            for order in behavior.unit.orders:
                if item := ITEM_BY_ABILITY.get(order.ability.exact_id):
                    self.pending_by_type[item].append(behavior)
        else:
            self.pending_by_type[behavior.unit.type_id].append(behavior)

    def add_unit(self, unit: Unit) -> AIUnit | None:
        if unit.type_id in IGNORED_UNIT_TYPES:
            return None
        elif unit.is_mine:
            behavior = self.create_unit(unit)
            if isinstance(behavior, Worker):
                self.ai.resource_manager.add_harvester(behavior)
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
        elif unit.type_id in WORKERS:
            return Worker(self.ai, unit)
        elif unit.type_id in {
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORDTRANSPORT,
        }:
            return Overlord(self.ai, unit)
        elif unit.type_id == UnitTypeId.QUEEN:
            return Queen(self.ai, unit)
        else:
            return Army(self.ai, unit)

    def update_tags(self) -> None:
        unit_by_tag = {u.tag: u for u in self.ai.all_own_units}
        for tag, unit in self.units.items():
            unit.unit = unit_by_tag.get(tag) or unit.unit

    def update_all_units(self) -> None:
        self.update_tags()
        self.update_tables()
        self.unit_by_position = {u.position: u for u in chain(self.ai.all_own_units, self.ai.all_enemy_units)}
        self.unit_positions = list(self.unit_by_position.keys())
        self.unit_tree = cKDTree(np.array(self.unit_positions))

    def units_in_circle(self, position: Point2, radius: float) -> Iterable[Unit]:
        result = self.unit_tree.query_ball_point(position, radius)
        return (self.unit_by_position[self.unit_positions[i]] for i in result)
