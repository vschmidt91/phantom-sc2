from typing import Iterable, Optional

from sc2.position import Point2

from ..behaviors.gather import GatherBehavior
from ..units.structure import Structure
from .mineral_patch import MineralPatch
from .resource_base import ResourceBase
from .resource_group import ResourceGroup
from .vespene_geyser import VespeneGeyser

STATIC_DEFENSE_OFFSET = 4.25


class Base(ResourceGroup[ResourceBase]):
    def __init__(
        self,
        position: Point2,
        mineral_patches: Iterable[MineralPatch],
        vespene_geysers: Iterable[VespeneGeyser],
    ):
        self.townhall: Optional[Structure] = None
        self.static_defense: Optional[Structure] = None
        self.mineral_patches: ResourceGroup[MineralPatch] = ResourceGroup(
            sorted(mineral_patches, key=lambda m: m.position.distance_to(position))
        )
        self.vespene_geysers: ResourceGroup[VespeneGeyser] = ResourceGroup(
            sorted(vespene_geysers, key=lambda g: g.position.distance_to(position))
        )
        super().__init__([self.mineral_patches, self.vespene_geysers], position)

        static_defense_position = Point2(self.position.towards(self.mineral_patches.position, STATIC_DEFENSE_OFFSET))
        static_defense_position = static_defense_position.rounded.offset((0.0, 0.0))
        self.static_defense_position = static_defense_position

    def split_initial_workers(self, harvesters: Iterable[GatherBehavior]):
        harvesters = set(harvesters)
        for _ in range(len(harvesters)):
            for patch in self.mineral_patches:
                if not patch.unit:
                    continue
                harvester = min(
                    harvesters, key=lambda h: h.unit.position.distance_to(patch.unit.position), default=None
                )
                if not harvester:
                    return
                harvesters.remove(harvester)
                harvester.set_gather_target(patch)
