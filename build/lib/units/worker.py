from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.unit import Unit, UnitCommand

from ..behaviors.gather import GatherBehavior
from ..modules.combat import CombatBehavior
from ..modules.dodge import DodgeBehavior
from ..modules.macro import MacroBehavior
from ..modules.module import AIModule

if TYPE_CHECKING:
    from ..ai_base import AIBase


class WorkerManager(AIModule):
    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)

    async def on_step(self) -> None:
        self.draft_civilians()
        pass

    def draft_civilians(self) -> None:
        if (
            self.ai.combat.confidence < 1 / 2
            and 0
            == self.ai.count(
                UnitTypeId.SPAWNINGPOOL, include_pending=False, include_planned=False
            )
            # and 100 < self.ai.time < 180
        ):
            worker = next(
                (
                    w
                    for w in self.ai.unit_manager.units.values()
                    if isinstance(w, Worker) and not w.is_drafted
                ),
                None,
            )
            if worker:
                worker.is_drafted = True
                worker.remove_gather_target()
        # else:
        elif 2 / 3 < self.ai.combat.confidence:
            worker = min(
                (
                    w
                    for w in self.ai.unit_manager.units.values()
                    if isinstance(w, Worker) and w.is_drafted
                ),
                key=lambda w: w.state.shield_health_percentage,
                default=None,
            )
            if worker:
                worker.is_drafted = False
                self.ai.resource_manager.add_harvester(worker)


class Worker(DodgeBehavior, CombatBehavior, MacroBehavior, GatherBehavior):
    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)
        self.is_drafted: bool = False

    def wants_to_fight(self) -> bool:
        return (
            1 < self.ai.combat.ground_dps[self.state.position.rounded]
        ) or self.is_drafted
    
    def on_step(self) -> None:
        if self.plan is not None:
            self.remove_gather_target()
        return super().on_step()

    def get_command(self) -> Optional[UnitCommand]:
        if command := self.dodge():
            return command
        elif command := self.fight():
            return command
        elif (
            self.state.health_percentage < 0.3
            and UpgradeId.BURROW in self.ai.state.upgrades
            and not self.state.is_burrowed
        ):
            return self.state(AbilityId.BURROWDOWN)
        elif self.state.is_burrowed:
            if self.ai.combat.ground_dps[self.state.position.rounded] < 1:
                return self.state(AbilityId.BURROWUP)
            else:
                return None
        elif command := self.macro():
            return command
        elif command := self.gather():
            return command
        else:
            return None
        # return self.dodge() or self.fight() or self.macro() or self.gather()
