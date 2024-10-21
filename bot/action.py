from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from ares import AresBot
from ares.consts import UnitRole
from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.unit_command import UnitCommand

from utils import time_to_reach


class Action(ABC):
    @abstractmethod
    async def execute(self, bot: AresBot) -> bool:
        raise NotImplementedError


class DoNothing(Action):
    async def execute(self, bot: AresBot) -> bool:
        return True


@dataclass
class AttackMove(Action):
    unit: Unit
    target: Point2

    async def execute(self, bot: AresBot) -> bool:
        return self.unit.attack(self.target)


@dataclass
class Move(Action):
    unit: Unit
    target: Point2

    async def execute(self, bot: AresBot) -> bool:
        return self.unit.move(self.target)


@dataclass
class HoldPosition(Action):
    unit: Unit

    async def execute(self, bot: AresBot) -> bool:
        return self.unit.stop()


@dataclass
class UseAbility(Action):
    unit: Unit
    ability: AbilityId
    target: Optional[Point2 | Unit] = None

    async def execute(self, bot: AresBot) -> bool:
        return self.unit(self.ability, target=self.target)


@dataclass
class Build(Action):
    unit: Unit
    type_id: UnitTypeId
    near: Point2

    async def execute(self, bot: AresBot) -> bool:
        logger.info(self)
        bot.mediator.assign_role(tag=self.unit.tag, role=UnitRole.PERSISTENT_BUILDER)
        if placement := await bot.find_placement(self.type_id, near=self.near):
            if bot.can_afford(self.type_id):
                return self.unit.build(self.type_id, placement)
            elif self.unit.is_carrying_resource:
                return self.unit.return_resource()
            else:
                return self.unit.move(placement)
                # cost_eta = 5.0
                # movement_eta = 1.2 * time_to_reach(self.unit, placement)
                # if self.unit.is_carrying_resource:
                #     movement_eta += 3.0
                # if cost_eta <= movement_eta:
                #     elif 1e-3 < self.unit.distance_to(placement):
                #         return self.unit.move(placement)

        else:
            return False


@dataclass
class Mine(Action):
    unit: Unit
    move_target: Point2
    target: Unit

    async def execute(self, bot: AresBot) -> bool:
        return self.unit.move(self.move_target) and self.unit.smart(self.target, queue=True)


@dataclass
class Train(Action):
    trainer: Unit
    unit: UnitTypeId

    async def execute(self, bot: AresBot) -> UnitCommand | None:
        return self.trainer.train(self.unit)


@dataclass
class Research(Action):
    researcher: Unit
    upgrade: UpgradeId

    async def execute(self, bot: AresBot) -> UnitCommand | None:
        return self.researcher.research(self.upgrade)
