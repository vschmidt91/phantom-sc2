from typing import Iterable, TypeAlias

from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit

from bot.common.action import Action, UseAbility
from bot.common.assignment import Assignment
from bot.common.constants import ENERGY_COST

InjectAssignment: TypeAlias = Assignment[int, int]
InjectAction: TypeAlias = Assignment[Unit, Action]


class InjectState:

    assignment = InjectAssignment({})

    def inject_with(self, queen: Unit) -> Action | None:
        if queen.energy < ENERGY_COST[AbilityId.EFFECT_INJECTLARVA]:
            return None
        if not (target_tag := self.assignment.get(queen.tag)):
            return None
        return UseAbility(queen, AbilityId.EFFECT_INJECTLARVA, target=target_tag)

    def step(self, queens: Iterable[Unit], targets: Iterable[Unit]) -> InjectAction:

        queens_dict = {q.tag: q for q in queens}
        targets_dict = {t.tag: t for t in targets}

        # unassign
        for q, t in self.assignment.items():
            if q not in queens_dict or t not in targets_dict:
                logger.info(f"Removing inject assignment: {q=} to {t=}")
                self.assignment -= {q}

        # assign
        unassigned_queens_set = set(queens_dict.keys()) - set(self.assignment.keys())
        unassigned_queens = sorted(unassigned_queens_set, key=lambda q: queens_dict[q].energy, reverse=True)
        unassinged_targets = set(targets_dict.keys()) - set(self.assignment.values())
        for q in unassigned_queens:
            if not any(unassinged_targets):
                break
            t = min(unassinged_targets, key=lambda t: targets_dict[t].distance_to(queens_dict[q]))
            self.assignment += {q: t}
            unassinged_targets.remove(t)

        return Assignment({q: a for q in queens if (a := self.inject_with(q))})
