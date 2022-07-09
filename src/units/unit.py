from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

from sc2.unit import Unit, UnitCommand
from sc2.position import Point2

from ..ai_component import AIComponent

if TYPE_CHECKING:
    from ..ai_base import AIBase


class AIUnit(ABC, AIComponent):

    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai)
        self.unit = unit

    def on_step(self) -> None:
        pass

    @property
    def value(self) -> float:
        health = self.unit.health + self.unit.shield
        dps = max(self.unit.ground_dps, self.unit.air_dps)
        return health * dps


class EnemyUnit(AIUnit):

    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)
        self.estimated_velocity: Point2 = Point2((0.0, 0.0))
        self.previous_position: Point2 = self.unit.position
        self.previous_position_time: float = self.ai.time

    def on_step(self) -> None:
        dt = self.ai.time - self.previous_position_time
        dx = self.unit.position - self.previous_position
        self.estimated_velocity = dx / max(1e-3, dt)
        self.previous_position = self.unit.position
        self.previous_position_age = self.ai.time

    @property
    def is_snapshot(self) -> bool:
        return self.unit.game_loop == self.ai.state.game_loop


class CommandableUnit(AIUnit):

    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)

    def on_step(self) -> None:
        if (
            (command := self.get_command())
            and not any(self.ai.order_matches_command(o, command) for o in command.unit.orders)
            and not self.ai.do(command, subtract_cost=False, subtract_supply=False)
        ):
            logging.error("command failed: %s", command)

    @abstractmethod
    def get_command(self) -> Optional[UnitCommand]:
        raise NotImplementedError()


class IdleBehavior(CommandableUnit):

    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)

    def get_command(self) -> Optional[UnitCommand]:
        return None
