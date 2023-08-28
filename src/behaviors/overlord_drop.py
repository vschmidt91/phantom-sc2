from __future__ import annotations

import random
from typing import Optional, Set

from sc2.unit import AbilityId, Point2, UnitCommand, UnitTypeId

from ..modules.module import AIModule
from ..units.unit import AIUnit, Behavior


class OverlordDropMemberBehavior(Behavior):
    def __init__(self, unit: AIUnit):
        super().__init__(unit)
        self.dropper: Optional[OverlordDropBehavior] = None

    def execute_overlord_drop(self) -> Optional[UnitCommand]:
        if not self.dropper:
            return None
        return self.unit.state(AbilityId.SMART, self.dropper.unit.state)


class OverlordDropBehavior(Behavior):
    def __init__(self, unit: AIUnit):
        super().__init__(unit)
        self.drop_target: Optional[Point2] = None
        self.assigned_to_drop: Set[OverlordDropMemberBehavior] = set()

    @property
    def can_drop(self) -> bool:
        return self.unit.state.type_id == UnitTypeId.OVERLORDTRANSPORT

    def execute_overlord_drop(self) -> Optional[UnitCommand]:
        if not self.drop_target:
            return None

        self.assigned_to_drop = {
            u
            for u in self.ai.unit_manager.behavior_of_type(OverlordDropMemberBehavior)
            if u.dropper == self
        }

        cargo_assigned = sum(u.unit.state.cargo_size for u in self.assigned_to_drop)

        if cargo_assigned < self.unit.state.cargo_max:
            assign = next(
                (
                    u
                    for u in self.ai.unit_manager.behavior_of_type(OverlordDropMemberBehavior)
                    if (
                        u.dropper == None
                        and 0 < u.unit.state.cargo_size < self.unit.state.cargo_left
                        and not self.ai.enemy_main[u.unit.state.position.rounded]
                    )
                ),
                None,
            )
            if assign:
                assign.dropper = self

        if cargo_assigned <= self.unit.state.cargo_used:
            if self.ai.enemy_main[self.unit.state.position.rounded]:
                for u in self.assigned_to_drop:
                    u.dropper = None
                return self.unit.state(
                    AbilityId.UNLOADALLAT_OVERLORD, self.unit.state.position
                )
            else:
                return self.unit.state.move(self.drop_target)
        else:
            return self.unit.state.move(self.ai.game_info.map_center)


class OverlordDropManager(AIModule):
    def __init__(self, ai: "AIBase") -> None:
        super().__init__(ai)
        self.active_drops: Set[OverlordDropBehavior] = set()
        self.assigned_to_drop: Set[OverlordDropMemberBehavior] = set()

    async def on_step(self) -> None:
        self.assigned_to_drop = {
            u.unit.state.tag
            for drop in self.active_drops
            for u in drop.assigned_to_drop
        }

        self.active_drops = {
            u
            for u in self.ai.unit_manager.behavior_of_type(OverlordDropBehavior)
            if u.drop_target
        }

        if len(self.active_drops) < 1:
            dropper = next(
                (
                    u
                    for u in self.ai.unit_manager.behavior_of_type(OverlordDropBehavior)
                    if (
                        u.can_drop
                        and not u.drop_target
                    )
                ),
                None,
            )
            if dropper:
                target = random.choice(self.ai.enemy_start_locations)
                dropper.drop_target = target

        return await super().on_step()
