from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.unit import Unit

from .base import BotBase


class Action(ABC):
    @abstractmethod
    async def execute(self, bot: BotBase) -> bool:
        raise NotImplementedError


class DoNothing(Action):
    async def execute(self, bot: BotBase) -> bool:
        return True


@dataclass
class AttackMove(Action):
    unit: Unit
    target: Point2

    async def execute(self, bot: BotBase) -> bool:
        return self.unit.attack(self.target)


@dataclass
class Move(Action):
    unit: Unit
    target: Point2

    async def execute(self, bot: BotBase) -> bool:
        return self.unit.move(self.target)


@dataclass
class HoldPosition(Action):
    unit: Unit

    async def execute(self, bot: BotBase) -> bool:
        return self.unit.stop()


@dataclass
class UseAbility(Action):
    unit: Unit
    ability: AbilityId
    target: Optional[Point2 | Unit] = None

    async def execute(self, bot: BotBase) -> bool:
        return self.unit(self.ability, target=self.target)
