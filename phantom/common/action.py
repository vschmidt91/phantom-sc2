from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.unit import Unit


class Action(ABC):
    @abstractmethod
    async def execute(self, unit: Unit) -> bool:
        raise NotImplementedError


@dataclass(frozen=True)
class Move(Action):
    target: Point2

    async def execute(self, unit: Unit) -> bool:
        return unit.move(self.target)


@dataclass(frozen=True)
class MovePath(Action):
    path: Sequence[Point2]

    async def execute(self, unit: Unit) -> bool:
        return all(unit.move(t, queue=i > 0) for i, t in enumerate(self.path))


@dataclass(frozen=True)
class HoldPosition(Action):
    async def execute(self, unit: Unit) -> bool:
        if unit.is_moving:
            return unit.stop()
        else:
            return unit.hold_position()


@dataclass(frozen=True)
class Smart(Action):
    target: Unit

    async def execute(self, unit: Unit) -> bool:
        return unit.smart(target=self.target)


@dataclass(frozen=True)
class UseAbility(Action):
    ability: AbilityId
    target: Point2 | Unit | None = None

    async def execute(self, unit: Unit) -> bool:
        return unit(self.ability, target=self.target)


@dataclass(frozen=True)
class Attack(Action):
    target: Point2 | Unit

    async def execute(self, unit: Unit) -> bool:
        if isinstance(self.target, Point2):
            return unit.attack(self.target)
        elif self.target.is_memory:
            return unit.attack(self.target.position)
        else:
            return unit.attack(self.target)
