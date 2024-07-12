from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from sc2.unit_command import UnitCommand
from sc2.unit import Union

from ..units.structure import Structure
from ..resources.resource_base import ResourceBase
from ..resources.mineral_patch import MineralPatch
from ..resources.vespene_geyser import VespeneGeyser
from ..units.unit import AIUnit
from ..utils import *
if TYPE_CHECKING:
    from ..ai_base import AIBase


class GatherBehavior(AIUnit):

    def __init__(self, ai: AIBase, unit: Unit):

        super().__init__(ai, unit)

        self.gather_target: Optional[ResourceBase] = None
        self.command_queue: Optional[Unit] = None
        self.return_target: Optional[Structure] = None

        self.ai.resource_manager.add_harvester(self)

    def set_gather_target(self, gather_target: ResourceBase) -> None:
        self.gather_target = gather_target
        self.return_target = min(
            self.ai.unit_manager.townhalls,
            key=lambda th: th.unit.distance_to(gather_target.position),
            default=None,
        )

    def gather(self) -> Optional[UnitCommand]:

        if not self.gather_target:
            return None
        elif not self.return_target:
            return None
        elif not self.return_target.unit or self.return_target.is_snapshot:
            self.set_gather_target(self.gather_target)
            return None
        elif not self.gather_target.remaining:
            return None
        elif not self.unit:
            return None

        target = None
        if isinstance(self.gather_target, MineralPatch):
            target = self.gather_target.unit
        elif isinstance(self.gather_target, VespeneGeyser):
            if self.gather_target.structure:
                target = self.gather_target.structure.unit

        if not target:
            self.gather_target = None
            return None
        elif self.command_queue:
            self.command_queue, target = None, self.command_queue
            return self.unit.smart(target, queue=True)
        # elif self.unit.is_carrying_resource:
        #     self.unit(AbilityId.SMART, self.return_target.unit, True)
        elif len(self.unit.orders) == 1:
            if self.unit.is_returning:
                townhall = self.return_target.unit
                move_target = townhall.position.towards(self.unit, townhall.radius + self.unit.radius)
                if 0.75 < self.unit.position.distance_to(move_target) < 1.5:
                    self.command_queue = townhall
                    return self.unit.move(move_target)
                    # self.unit(AbilityId.SMART, townhall, True)
            elif self.unit.is_gathering:
                if self.unit.order_target != target.tag:
                    return self.unit.smart(target)
                else:
                    move_target = None
                    if isinstance(self.gather_target, MineralPatch):
                        move_target = self.gather_target.speedmining_target
                    if not move_target:
                        move_target = target.position.towards(self.unit, target.radius + self.unit.radius)
                    if 0.75 < self.unit.position.distance_to(move_target) < 1.75:
                        self.command_queue = target
                        return self.unit.move(move_target)
                        # self.unit.move(move_target)
                        # self.unit(AbilityId.SMART, target, True)
            else:
                return self.unit.smart(target)
        elif self.unit.is_idle:
            return self.unit.smart(target)
            
        return None
