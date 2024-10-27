from abc import ABC
from typing import Iterable

from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit

from ..action import Action, UseAbility
from ..constants import ENERGY_COST
from .base import Component


class Inject(Component, ABC):

    _inject_assignment: dict[int, int] = dict()

    def do_injects(self) -> Iterable[Action]:
        if 200 <= self.larva.amount + self.supply_used:
            return
        for queen_tag, target_tag in list(self._inject_assignment.items()):
            if queen := self.unit_tag_dict.get(queen_tag):
                if target := self.unit_tag_dict.get(target_tag):
                    if ENERGY_COST[AbilityId.EFFECT_INJECTLARVA] <= queen.energy:
                        yield UseAbility(queen, AbilityId.EFFECT_INJECTLARVA, target=target)
                else:
                    del self._inject_assignment[queen_tag]
                    logger.info(f"Unassigning {queen=} from dead {target_tag=}")
            else:
                del self._inject_assignment[queen_tag]
                logger.info(f"Unassigning dead {queen=} from {target_tag=}")

    def assign_queens(self, queens: Iterable[Unit], townhalls: Iterable[Unit]) -> None:
        assigned_bases = self._inject_assignment.values()
        targets = [th for th in townhalls if th.is_ready and th.tag not in assigned_bases]

        if queen := next((queen for queen in queens if queen.tag not in self._inject_assignment), None):
            if target := min(targets, key=lambda b: b.distance_to(queen), default=None):
                self._inject_assignment[queen.tag] = target.tag
