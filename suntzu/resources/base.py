
from typing import Dict, Iterable, Set, List, Optional
from itertools import chain

from s2clientprotocol.sc2api_pb2 import Observation

from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from .mineral_patch import MineralPatch
from .vespene_geyser import VespeneGeyser
from .resource import Resource
from .resource_group import ResourceGroup

class Base(ResourceGroup[Resource]):

    def __init__(self,
        townhall_position: Point2,
        minerals: Iterable[Point2],
        gasses: Iterable[Point2],
    ):
        self.mineral_patches: ResourceGroup[MineralPatch] = ResourceGroup(sorted(
            (MineralPatch(m) for m in minerals),
            key = lambda m : m.position.distance_to(townhall_position)
        ))
        self.vespene_geysers: ResourceGroup[VespeneGeyser] = ResourceGroup(sorted(
            (VespeneGeyser(g) for g in gasses),
            key = lambda g : g.position.distance_to(townhall_position)
        ))
        self.mineral_patches.balance_aggressively = True
        self.vespene_geysers.balance_aggressively = True
        self.townhall: Optional[int] = None
        super().__init__([self.mineral_patches, self.vespene_geysers], townhall_position)

    @property
    def harvester_target(self) -> int:
        if self.townhall == None:
            return 0
        return super().harvester_target

    def update(self, observation: Observation):
        if self.townhall == None:
            return
        super().update(observation)