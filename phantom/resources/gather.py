from dataclasses import dataclass

from sc2.position import Point2
from sc2.unit import Unit

from phantom.common.action import Action


@dataclass
class GatherAction(Action):
    target: Unit
    speedmining_position: Point2

    async def execute(self, unit: Unit) -> bool:
        if unit.order_target != self.target.tag:
            return unit.smart(self.target)
        if 0.75 < unit.distance_to(self.speedmining_position) < 1.75:
            return unit.move(self.speedmining_position) and unit.smart(self.target, queue=True)
        else:
            return True


@dataclass
class ReturnResource(Action):
    return_target: Unit
    speedmining_position: Point2

    async def execute(self, unit: Unit) -> bool:
        move_target = self.speedmining_position
        if 0.75 < unit.position.distance_to(move_target) < 1.5:
            return unit.move(move_target) and unit.smart(self.return_target, queue=True)
        else:
            return True
