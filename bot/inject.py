from typing import Iterable

from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit

from .action import Action, UseAbility
from .constants import ENERGY_COST


class Inject:

    _inject_assignment: dict[int, int] = dict()

    def get_target(self, queen: Unit) -> int | None:
        return self._inject_assignment.get(queen.tag)

    def inject_with(self, queen: Unit) -> Action | None:
        if queen.energy < ENERGY_COST[AbilityId.EFFECT_INJECTLARVA]:
            return None
        elif not (target_tag := self._inject_assignment.get(queen.tag)):
            return None
        return UseAbility(queen, AbilityId.EFFECT_INJECTLARVA, target=target_tag)

    def assign(self, queens: Iterable[Unit], targets: Iterable[Unit]) -> None:

        queens_dict = {q.tag: q for q in queens}
        targets_dict = {t.tag: t for t in targets}

        # unassign
        for queen, target in list(self._inject_assignment.items()):
            if queen not in queens_dict or target not in targets_dict:
                logger.info(f"Removing inject assignment: {queen=} to {target=}")
                del self._inject_assignment[queen]

        # assign
        unassigned_queens_set = set(queens_dict.keys()) - set(self._inject_assignment.keys())
        unassigned_queens = sorted(unassigned_queens_set, key=lambda q: queens_dict[q].energy, reverse=True)
        unassinged_targets = set(targets_dict.keys()) - set(self._inject_assignment.values())
        for q in unassigned_queens:
            queen = queens_dict[q]
            if not any(unassinged_targets):
                break
            target = min(unassinged_targets, key=lambda t: targets_dict[t].distance_to(queen))
            self._inject_assignment[q] = target
            unassinged_targets.remove(target)