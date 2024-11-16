from dataclasses import dataclass

from ares import AresBot
from sc2.position import Point2
from sc2.unit import Unit

from bot.common.action import Action


@dataclass
class GatherAction(Action):
    unit: Unit
    target: Unit
    speedmining_position: Point2 | None = None

    async def execute(self, bot: AresBot) -> bool:
        if self.unit.order_target != self.target.tag:
            return self.unit.smart(self.target)
        move_target = self.speedmining_position or self.target.position.towards(
            self.unit, self.target.radius + self.unit.radius
        )
        if 0.75 < self.unit.distance_to(move_target) < 1.75:
            return self.unit.move(move_target) and self.unit.smart(self.target, queue=True)
        else:
            return True


@dataclass
class ReturnResource(Action):
    unit: Unit
    return_target: Unit

    async def execute(self, bot: AresBot) -> bool:
        move_target = self.return_target.position.towards(self.unit, self.return_target.radius + self.unit.radius)
        if 0.75 < self.unit.position.distance_to(move_target) < 1.5:
            return self.unit.move(move_target) and self.unit.smart(self.return_target, queue=True)
        else:
            return True
