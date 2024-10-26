from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from sc2.data import race_townhalls
from sc2.unit import Unit
from sc2.units import Units

from ..components.macro import MacroId
from ..constants import ITEM_BY_ABILITY
from .module import AIModule

if TYPE_CHECKING:
    pass


class UnitManager(AIModule):
    actual_by_type: defaultdict[MacroId, list[Unit]] = defaultdict(list)
    pending_by_type: defaultdict[MacroId, list[Unit]] = defaultdict(list)

    @property
    def townhalls(self) -> Units:
        return self.ai.units(race_townhalls[self.ai.race])

    def update_tables(self):
        self.actual_by_type.clear()
        self.pending_by_type.clear()

        for unit in self.ai.all_own_units:
            if unit.is_ready:
                self.actual_by_type[unit.type_id].append(unit)
                for order in unit.orders:
                    if item := ITEM_BY_ABILITY.get(order.ability.exact_id):
                        self.pending_by_type[item].append(unit)
            else:
                self.pending_by_type[unit.type_id].append(unit)

        for upgrade in self.ai.state.upgrades:
            self.actual_by_type[upgrade] = [self.ai.all_units[0]]

    def update_all_units(self) -> None:
        self.update_tables()

    #     self.unit_by_position = {u.position: u for u in chain(self.ai.all_own_units, self.ai.all_enemy_units)}
    #     self.unit_positions = list(self.unit_by_position.keys())
    #     self.unit_tree = cKDTree(np.array(self.unit_positions))
    #
    # def units_in_circle(self, position: Point2, radius: float) -> Iterable[Unit]:
    #     result = self.unit_tree.query_ball_point(position, radius)
    #     return (self.unit_by_position[self.unit_positions[i]] for i in result)
