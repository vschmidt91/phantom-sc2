from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import numpy as np

from sc2.bot_ai import Race
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.unit import Unit, UnitCommand

from ..modules.module import AIModule
from ..behaviors.gather import GatherBehavior
from ..modules.combat import CombatBehavior, InfluenceMapEntry
from ..modules.dodge import DodgeBehavior
from ..modules.macro import MacroBehavior

if TYPE_CHECKING:
    from ..ai_base import AIBase


class WorkerManager(AIModule):

    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)

    async def on_step(self) -> None:
        # self.draft_civilians()
        pass

    def draft_civilians(self) -> None:

        if (
            self.ai.combat.confidence < 1/2
            and 0 == self.ai.count(UnitTypeId.SPAWNINGPOOL, include_pending=False, include_planned=False)
            and 100 < self.ai.time < 180
        ):
                worker = next(
                    (w
                        for w in self.ai.unit_manager.units.values()
                        if isinstance(w, Worker) and not w.is_drafted
                    ),
                    None
                )
                if worker:
                    worker.is_drafted = True
        else:
        # elif 2/3 < self.ai.combat.confidence:
            worker = min(
                (
                    w
                    for w in self.ai.unit_manager.units.values()
                    if isinstance(w, Worker) and w.is_drafted
                ),
                key=lambda w : w.unit.shield_health_percentage,
                default=None
            )
            if worker:
                worker.is_drafted = False


class Worker(DodgeBehavior, CombatBehavior, MacroBehavior, GatherBehavior):

    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)
        self.is_drafted: bool = False

    def get_command(self) -> Optional[UnitCommand]:
        if command := self.dodge():
            return command
        elif self.is_drafted:
            return self.fight()
        elif (
            self.ai.enemy_race == Race.Protoss
            and 1 < self.ai.combat.ground_dps[self.unit.position.rounded]
        ):
            if UpgradeId.BURROW in self.ai.state.upgrades:
                return self.unit(AbilityId.BURROWDOWN)
            else:
                return self.fight()
        elif self.unit.is_burrowed:
            return self.unit(AbilityId.BURROWUP)
        elif command := self.macro():
            return command
        elif command := self.gather():
            return command
        else:
            return None
        # return self.dodge() or self.fight() or self.macro() or self.gather()
