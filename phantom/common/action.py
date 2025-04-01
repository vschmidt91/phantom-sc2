from abc import ABC, abstractmethod
from dataclasses import dataclass

from sc2.bot_ai import BotAI
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.unit import Unit


class Action(ABC):
    @abstractmethod
    async def execute(self, bot: BotAI) -> bool:
        raise NotImplementedError


class DoNothing(Action):
    async def execute(self, bot: BotAI) -> bool:
        return True


@dataclass(frozen=True)
class Move(Action):
    unit: Unit
    target: Point2

    async def execute(self, bot: BotAI) -> bool:
        return self.unit.move(self.target)


@dataclass(frozen=True)
class HoldPosition(Action):
    unit: Unit

    async def execute(self, bot: BotAI) -> bool:
        return self.unit.stop()


@dataclass(frozen=True)
class Smart(Action):
    unit: Unit
    target: Unit

    async def execute(self, bot: BotAI) -> bool:
        return self.unit.smart(target=self.target)


@dataclass(frozen=True)
class UseAbility(Action):
    unit: Unit
    ability: AbilityId
    target: Point2 | Unit | None = None

    async def execute(self, bot: BotAI) -> bool:
        return self.unit(self.ability, target=self.target)


@dataclass(frozen=True)
class Attack(Action):
    unit: Unit
    target: Unit

    async def execute(self, bot: BotAI) -> bool:
        if self.target.is_memory:
            return self.unit.attack(self.target.position)
        else:
            return self.unit.attack(self.target)
