from __future__ import annotations

from typing import Iterable, List, Optional, TYPE_CHECKING

from sc2.position import Point2

if TYPE_CHECKING:
    from src.ai_base import AIBase

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
        ai: AIBase,
        position: Point2,
        mineral_patches: Iterable[MineralPatch],
        vespene_geysers: Iterable[VespeneGeyser],
    ) -> None:
        self.townhall: Optional[Structure] = None
        self.static_defense: Optional[Structure] = None
        self.mineral_patches: ResourceGroup[MineralPatch] = ResourceGroup(
            ai,
            sorted(mineral_patches, key=lambda m: m.position.distance_to(position)),
        )
        self.vespene_geysers: ResourceGroup[VespeneGeyser] = ResourceGroup(
            ai,
            sorted(vespene_geysers, key=lambda g: g.position.distance_to(position)),
        )
        super().__init__(ai, [self.mineral_patches, self.vespene_geysers], position)

        static_defense_position = Point2(
            self.position.towards(self.mineral_patches.position, STATIC_DEFENSE_OFFSET)
        )
        static_defense_position = static_defense_position.rounded.offset((0.0, 0.0))
        self.static_defense_position = static_defense_position

    def split_initial_workers(self, harvesters: Iterable[GatherBehavior]):
        harvesters = set(harvesters)
        for _ in range(len(harvesters)):
            for patch in self.mineral_patches:
                if not patch.unit:
                    continue
                harvester = min(
                    harvesters,
                    key=lambda h: h.unit.state.position.distance_to(patch.unit.position),
                    default=None,
                )
                if not harvester:
                    return
                harvesters.remove(harvester)
                harvester.set_gather_target(patch)
