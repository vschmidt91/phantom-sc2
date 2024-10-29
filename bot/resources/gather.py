from dataclasses import dataclass

from ares import AresBot
from sc2.position import Point2
from sc2.unit import Unit

from ..action import Action
from .mineral_patch import MineralPatch
from .resource_unit import ResourceUnit


@dataclass
class GatherAction(Action):
    unit: Unit
    gather_target: ResourceUnit

    async def execute(self, bot: AresBot) -> bool:
        if not (target := self.gather_target.target_unit):
            return False
        elif self.unit.order_target != target.tag:
            return self.unit.smart(target)
        move_target: Point2
        if isinstance(self.gather_target, MineralPatch):
            move_target = self.gather_target.speedmining_target
        else:
            move_target = target.position.towards(self.unit, target.radius + self.unit.radius)
        if 0.75 < self.unit.distance_to(move_target) < 1.75:
            return self.unit.move(move_target) and self.unit.smart(target, queue=True)
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
