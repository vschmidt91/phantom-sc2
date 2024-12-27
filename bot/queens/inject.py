from dataclasses import dataclass
from typing import Iterable, TypeAlias

from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit

from bot.common.action import Action, UseAbility
from bot.common.assignment import Assignment
from bot.common.constants import ENERGY_COST

InjectAssignment: TypeAlias = Assignment[int, int]


@dataclass(frozen=True)
class Inject:

    assignment: InjectAssignment

    def get_target(self, queen: Unit) -> int | None:
        return self.assignment.get(queen.tag)

    def inject_with(self, queen: Unit) -> Action | None:
        if queen.energy < ENERGY_COST[AbilityId.EFFECT_INJECTLARVA]:
            return None
        elif not (target_tag := self.assignment.get(queen.tag)):
            return None
        return UseAbility(queen, AbilityId.EFFECT_INJECTLARVA, target=target_tag)

    def update(self, queens: Iterable[Unit], targets: Iterable[Unit]) -> "Inject":

        assignment = self.assignment
        queens_dict = {q.tag: q for q in queens}
        targets_dict = {t.tag: t for t in targets}

        # unassign
        for queen, target in assignment.items():
            if queen not in queens_dict or target not in targets_dict:
                logger.info(f"Removing inject assignment: {queen=} to {target=}")
                assignment -= {queen}

        # assign
        unassigned_queens_set = set(queens_dict.keys()) - set(assignment.keys())
        unassigned_queens = sorted(unassigned_queens_set, key=lambda q: queens_dict[q].energy, reverse=True)
        unassinged_targets = set(targets_dict.keys()) - set(assignment.values())
        for q in unassigned_queens:
            queen = queens_dict[q]
            if not any(unassinged_targets):
                break
            target = min(unassinged_targets, key=lambda t: targets_dict[t].distance_to(queen))
            assignment += {q: target}
            unassinged_targets.remove(target)

        return Inject(assignment)
