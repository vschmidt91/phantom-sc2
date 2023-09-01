from __future__ import annotations

from typing import Optional

from sc2.unit import Unit
from sc2.unit_command import UnitCommand
from sc2.position import Point3

from ..resources.mineral_patch import MineralPatch
from ..resources.resource_base import ResourceBase
from ..resources.vespene_geyser import VespeneGeyser
from ..units.structure import Structure
from ..units.unit import AIUnit, Behavior


class GatherBehavior(Behavior):
    def __init__(self, unit: AIUnit) -> None:
        super().__init__(unit)

        self.gather_target: Optional[ResourceBase] = None
        self.command_queue: Optional[Unit] = None
        self.return_target: Optional[Structure] = None

        self.ai.resource_manager.add_harvester(self)

    def on_step(self) -> None:
        if self.ai.debug:
            if self.gather_target is not None:
                position_from = Point3(
                    (
                        *self.unit.state.position,
                        self.ai.get_terrain_z_height(self.unit.state.position) + 0.5,
                    )
                )

                position_to = Point3(
                    (
                        *self.gather_target.position,
                        self.ai.get_terrain_z_height(self.gather_target.position) + 0.5,
                    )
                )

                self.ai.client.debug_line_out(
                    position_from, position_to, color=(0, 255, 0)
                )

    def set_gather_target(self, gather_target: ResourceBase) -> None:
        self.gather_target = gather_target
        self.return_target = min(
            self.ai.unit_manager.townhalls,
            key=lambda th: th.unit.state.position.distance_to(gather_target.position),
            default=None,
        )

    def remove_gather_target(self) -> None:
        self.gather_target = None
        self.return_target = None

    def gather(self) -> Optional[UnitCommand]:
        if not self.gather_target:
            return None
        elif not self.return_target:
            return None
        elif not self.return_target.unit.state or self.return_target.unit.is_snapshot:
            self.set_gather_target(self.gather_target)
            return None
        elif not self.gather_target.remaining:
            return None
        elif not self.unit.state:
            return None

        target = None
        if isinstance(self.gather_target, MineralPatch):
            target = self.gather_target.unit
        elif isinstance(self.gather_target, VespeneGeyser):
            if self.gather_target.structure:
                target = self.gather_target.structure.state

        if not target:
            self.remove_gather_target()
            return None
        elif self.command_queue:
            target = self.command_queue
            self.command_queue = None
            return self.unit.state.smart(target, queue=True)
        # elif self.unit.is_carrying_resource:
        #     self.unit(AbilityId.SMART, self.return_target.unit, True)
        elif len(self.unit.state.orders) == 1:
            if self.unit.state.is_returning:
                townhall = self.return_target.unit.state
                move_target = townhall.position.towards(
                    self.unit.state, townhall.radius + self.unit.state.radius
                )
                if 0.75 < self.unit.state.position.distance_to(move_target) < 1.5:
                    self.command_queue = townhall
                    return self.unit.state.move(move_target)
                    # self.unit(AbilityId.SMART, townhall, True)
            elif self.unit.state.is_gathering:
                if self.unit.state.order_target != target.tag:
                    return self.unit.state.smart(target)
                else:
                    move_target = None
                    if isinstance(self.gather_target, MineralPatch):
                        move_target = self.gather_target.speedmining_target
                    if not move_target:
                        move_target = target.position.towards(
                            self.unit.state, target.radius + self.unit.state.radius
                        )
                    if 0.75 < self.unit.state.position.distance_to(move_target) < 1.75:
                        self.command_queue = target
                        return self.unit.state.move(move_target)
                        # self.unit.move(move_target)
                        # self.unit(AbilityId.SMART, target, True)
            else:
                return self.unit.state.smart(target)
        elif self.unit.state.is_idle:
            return self.unit.state.smart(target)

        return None
