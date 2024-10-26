from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId

from ..action import Action, UseAbility
from ..constants import ENERGY_COST
from .component import Component

if TYPE_CHECKING:
    pass


class InjectManager(Component):

    _inject_assignment: dict[int, int] = dict()

    def do_injects(self) -> Iterable[Action]:
        for tag in list(self._inject_assignment.keys()):
            if tag not in self.unit_tag_dict:
                del self._inject_assignment[tag]
        self.assign_queens()
        for queen in self.unit_manager.actual_by_type[UnitTypeId.QUEEN]:
            if target_tag := self._inject_assignment.get(queen.tag):
                if target := self.unit_tag_dict.get(target_tag):
                    if ENERGY_COST[AbilityId.EFFECT_INJECTLARVA] <= queen.energy:
                        yield UseAbility(queen, AbilityId.EFFECT_INJECTLARVA, target=target)
                else:
                    del self._inject_assignment[queen.tag]
                    logger.info(f"Unassigning {queen=} from {target_tag=}")

    def assign_queens(self) -> None:

        queens = self.unit_manager.actual_by_type[UnitTypeId.QUEEN]
        assigned_bases = set(self._inject_assignment.values())
        targets = [
            townhall
            for townhall in self.townhalls
            if (
                townhall.is_ready
                and townhall.tag not in assigned_bases
                and BuffId.QUEENSPAWNLARVATIMER not in townhall.buffs
            )
        ]

        if queen := next((queen for queen in queens if queen.tag not in self._inject_assignment), None):
            if target := min(targets, key=lambda b: b.distance_to(queen), default=None):
                self._inject_assignment[queen.tag] = target.tag
