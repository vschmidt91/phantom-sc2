from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sc2.ids.buff_id import BuffId
from sc2.unit_command import UnitCommand

from ..constants import *
from ..modules.module import AIModule
from ..resources.base import Base
from ..units.unit import AIUnit
from ..utils import *

if TYPE_CHECKING:
    from ..ai_base import AIBase


class InjectManager(AIModule):
    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)

    async def on_step(self) -> None:
        self.assign_queen()

    def assign_queen(self) -> None:
        queens = [behavior for behavior in self.ai.unit_manager.units.values() if isinstance(behavior, InjectBehavior)]
        injected_bases = {q.inject_base for q in queens}

        queen = next((queen for queen in queens if not queen.inject_base), None)
        if queen:
            pos = queen.state.position
            queen.inject_base = min(
                (
                    base
                    for base in self.ai.resource_manager.bases
                    if (
                        base.townhall
                        and base not in injected_bases
                        and BuffId.QUEENSPAWNLARVATIMER not in base.townhall.state.buffs
                    )
                ),
                key=lambda b: b.position.distance_to(pos),
                default=None,
            )


class InjectBehavior(AIUnit):
    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)
        self.inject_base: Optional[Base] = None

    def inject(self) -> Optional[UnitCommand]:
        if not self.inject_base:
            return None

        if not self.inject_base.townhall:
            self.inject_base = None
            return None

        target = self.inject_base.position.towards(
            self.inject_base.mineral_patches.position,
            -(self.inject_base.townhall.state.radius + self.state.radius),
        )
        if 10 < self.state.position.distance_to(target):
            return self.state.move(target)
        elif self.inject_base.townhall.state.has_buff(BuffId.QUEENSPAWNLARVATIMER):
            return None
        elif ENERGY_COST[AbilityId.EFFECT_INJECTLARVA] <= self.state.energy:
            return self.state(AbilityId.EFFECT_INJECTLARVA, target=self.inject_base.townhall.state)

        return None
