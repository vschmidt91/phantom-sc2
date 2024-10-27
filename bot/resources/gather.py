from dataclasses import dataclass

from ares import AresBot
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.unit import Unit

from ..action import Action, UseAbility
from .resource_unit import ResourceUnit


@dataclass
class Mine(Action):
    unit: Unit
    move_target: Point2
    target: Unit

    async def execute(self, bot: AresBot) -> bool:
        return self.unit.move(self.move_target) and self.unit.smart(self.target, queue=True)


@dataclass
class GatherAction(Action):
    unit: Unit
    gather_target: ResourceUnit

    async def execute(self, bot: AresBot) -> bool:
        target = self.gather_target.target_unit
        return_target = min(
            bot.townhalls.ready,
            key=lambda th: th.distance_to(self.gather_target.position),
            default=None,
        )
        if not target:
            return False
        elif not return_target:
            return True
        elif not target.is_ready:
            return self.unit.move(target)
        elif not self.gather_target.remaining:
            return False

        elif len(self.unit.orders) == 1:
            if self.unit.is_returning:
                townhall = return_target
                move_target = townhall.position.towards(self.unit, townhall.radius + self.unit.radius)
                if 0.75 < self.unit.position.distance_to(move_target) < 1.5:
                    return await Mine(self.unit, move_target, townhall).execute(bot)
            elif self.unit.is_gathering:
                if self.unit.order_target != target.tag:
                    return await UseAbility(self.unit, AbilityId.SMART, target).execute(bot)
                else:
                    move_target = None
                    if hasattr(self.gather_target, "speedmining_target"):
                        move_target = self.gather_target.speedmining_target
                    if not move_target:
                        move_target = target.position.towards(self.unit, target.radius + self.unit.radius)
                    if 0.75 < self.unit.position.distance_to(move_target) < 1.75:
                        return await Mine(self.unit, move_target, target).execute(bot)
            else:
                return await UseAbility(self.unit, AbilityId.SMART, target).execute(bot)
        elif self.unit.is_idle:
            return await UseAbility(self.unit, AbilityId.SMART, target).execute(bot)

        return True
