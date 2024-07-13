from __future__ import annotations

import random
from typing import TYPE_CHECKING, Optional, Set

from sc2.unit import AbilityId, Point2, Unit, UnitCommand, UnitTypeId

from ..modules.module import AIModule
from ..units.unit import AIUnit

if TYPE_CHECKING:
    from ..ai_base import AIBase


class OverlordDropMemberBehavior(AIUnit):
    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)
        self.dropper: Optional[OverlordDropBehavior] = None

    def execute_overlord_drop(self) -> Optional[UnitCommand]:
        if not self.dropper:
            return None
        return self.unit(AbilityId.SMART, self.dropper.unit)


class OverlordDropBehavior(AIUnit):
    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)
        self.drop_target: Optional[Point2] = None
        self.assigned_to_drop: Set[OverlordDropMemberBehavior] = set()

    @property
    def can_drop(self) -> bool:
        return self.unit.type_id == UnitTypeId.OVERLORDTRANSPORT

    def execute_overlord_drop(self) -> Optional[UnitCommand]:
        if not self.drop_target:
            return None

        self.assigned_to_drop = {
            u
            for u in self.ai.unit_manager.units.values()
            if isinstance(u, OverlordDropMemberBehavior) and u.dropper == self
        }

        cargo_assigned = sum(u.unit.cargo_size for u in self.assigned_to_drop)

        if cargo_assigned < self.unit.cargo_max:
            assign = next(
                (
                    u
                    for u in self.ai.unit_manager.units.values()
                    if (
                        isinstance(u, OverlordDropMemberBehavior)
                        and not u.dropper
                        and 0 < u.unit.cargo_size < self.unit.cargo_left
                        and not self.ai.enemy_main[u.unit.position.rounded]
                    )
                ),
                None,
            )
            if assign:
                assign.dropper = self

        if cargo_assigned <= self.unit.cargo_used:
            if self.ai.enemy_main[self.unit.position.rounded]:
                for u in self.assigned_to_drop:
                    u.dropper = None
                return self.unit(AbilityId.UNLOADALLAT_OVERLORD, self.unit.position)
            else:
                return self.unit.move(self.drop_target)
        else:
            return self.unit.move(self.ai.game_info.map_center)


class OverlordDropManager(AIModule):
    def __init__(self, ai: "AIBase") -> None:
        super().__init__(ai)
        self.active_drops: Set[OverlordDropBehavior] = set()
        self.assigned_to_drop: Set[OverlordDropMemberBehavior] = set()

    async def on_step(self) -> None:
        self.assigned_to_drop = {u.unit.tag for drop in self.active_drops for u in drop.assigned_to_drop}

        self.active_drops = {
            u for u in self.ai.unit_manager.units.values() if isinstance(u, OverlordDropBehavior) and u.drop_target
        }

        if len(self.active_drops) < 1:
            dropper = next(
                (
                    u
                    for u in self.ai.unit_manager.units.values()
                    if (isinstance(u, OverlordDropBehavior) and u.can_drop and not u.drop_target)
                ),
                None,
            )
            if dropper:
                target = random.choice(self.ai.enemy_start_locations)
                dropper.drop_target = target

        return await super().on_step()
