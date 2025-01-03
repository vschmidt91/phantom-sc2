from abc import ABC, abstractmethod
from dataclasses import dataclass

from sc2.ids.ability_id import AbilityId
from sc2.position import Point2, Point3
from sc2.unit import Unit

from bot.common.main import BotBase


class Action(ABC):
    @abstractmethod
    async def execute(self, bot: BotBase) -> bool:
        raise NotImplementedError


class DoNothing(Action):
    async def execute(self, bot: BotBase) -> bool:
        return True


@dataclass(frozen=True)
class AttackMove(Action):
    unit: Unit
    target: Point2

    async def execute(self, bot: BotBase) -> bool:
        if bot.config["Debug"]:
            bot.client.debug_line_out(
                self.unit,
                Point3((self.target.x, self.target.y, bot.get_terrain_z_height(self.target) + 1.0)),
            )
        return self.unit.attack(self.target)


@dataclass(frozen=True)
class Move(Action):
    unit: Unit
    target: Point2

    async def execute(self, bot: BotBase) -> bool:
        return self.unit.move(self.target)


@dataclass(frozen=True)
class HoldPosition(Action):
    unit: Unit

    async def execute(self, bot: BotBase) -> bool:
        return self.unit.stop()


@dataclass(frozen=True)
class Smart(Action):
    unit: Unit
    target: Point2 | Unit | int | None = None

    async def execute(self, bot: BotBase) -> bool:
        target: Point2 | Unit | int | None
        if isinstance(self.target, int):
            if not (target := bot.unit_tag_dict.get(self.target)):
                return False
        else:
            target = self.target
        return self.unit.smart(target=target)


@dataclass(frozen=True)
class UseAbility(Action):
    unit: Unit
    ability: AbilityId
    target: Point2 | Unit | int | None = None

    async def execute(self, bot: BotBase) -> bool:
        target: Point2 | Unit | int | None
        if isinstance(self.target, int):
            if not (target := bot.unit_tag_dict.get(self.target)):
                return False
        else:
            target = self.target
        return self.unit(self.ability, target=target)


@dataclass(frozen=True)
class Attack(Action):
    unit: Unit
    target: Unit

    async def execute(self, bot: BotBase) -> bool:
        if bot.config["Debug"]:
            bot.client.debug_line_out(
                self.unit,
                self.target,
            )
        if self.target.is_memory:
            return self.unit.attack(self.target.position)
        else:
            return self.unit.attack(self.target)
