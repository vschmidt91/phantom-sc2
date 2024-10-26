from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from sc2.unit import Unit

from ..constants import ITEM_BY_ABILITY
from .base import Component
from .macro import MacroId

if TYPE_CHECKING:
    pass


class UnitManager(Component):
    actual_by_type: defaultdict[MacroId, list[Unit]] = defaultdict(list)
    pending_by_type: defaultdict[MacroId, list[Unit]] = defaultdict(list)

    def update_tables(self):
        self.actual_by_type.clear()
        self.pending_by_type.clear()

        for unit in self.all_own_units:
            if unit.is_ready:
                self.actual_by_type[unit.type_id].append(unit)
                for order in unit.orders:
                    if item := ITEM_BY_ABILITY.get(order.ability.exact_id):
                        self.pending_by_type[item].append(unit)
            else:
                self.pending_by_type[unit.type_id].append(unit)

        for upgrade in self.state.upgrades:
            self.actual_by_type[upgrade] = [self.all_units[0]]
