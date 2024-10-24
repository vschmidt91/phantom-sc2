from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Optional

from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.unit import Unit

from ..action import Action, UseAbility
from ..constants import ENERGY_COST
from ..modules.module import AIModule
from ..resources.base import Base
from ..units.unit import AIUnit

if TYPE_CHECKING:
    from ..ai_base import PhantomBot


class InjectManager(AIModule):
    def __init__(self, ai: PhantomBot) -> None:
        super().__init__(ai)

    def on_step(self) -> Iterable[Action]:
        self.assign_queen()

        for unit in self.ai.unit_manager.units.values():
            if isinstance(unit, InjectBehavior):
                if action := unit.inject():
                    yield action

    def assign_queen(self) -> None:
        queens = [behavior for behavior in self.ai.unit_manager.units.values() if isinstance(behavior, InjectBehavior)]
        injected_bases = {q.inject_base for q in queens}

        queen = next((queen for queen in queens if not queen.inject_base), None)
        if queen:
            pos = queen.unit.position
            queen.inject_base = min(
                (
                    base
                    for base in self.ai.resource_manager.bases
                    if (
                        base.townhall
                        and base not in injected_bases
                        and BuffId.QUEENSPAWNLARVATIMER not in base.townhall.unit.buffs
                    )
                ),
                key=lambda b: b.position.distance_to(pos),
                default=None,
            )


class InjectBehavior(AIUnit):
    def __init__(self, ai: PhantomBot, unit: Unit):
        super().__init__(ai, unit)
        self.inject_base: Optional[Base] = None

    def inject(self) -> Action | None:
        if not self.inject_base:
            return None
        if not self.inject_base.townhall:
            self.inject_base = None
            return None
        if ENERGY_COST[AbilityId.EFFECT_INJECTLARVA] <= self.unit.energy:
            return UseAbility(self.unit, AbilityId.EFFECT_INJECTLARVA, target=self.inject_base.townhall.unit)
        return None
