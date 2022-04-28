

from __future__ import annotations
from collections import defaultdict
from typing import TYPE_CHECKING, DefaultDict, Dict, Iterable, Set

from src.resources.resource_base import ResourceBase

from .mineral_patch import MineralPatch
from .vespene_geyser import VespeneGeyser
from .base import Base
from ..behaviors.gather import GatherBehavior
from .resource_group import ResourceGroup
from ..modules.module import AIModule
if TYPE_CHECKING:
    from ..ai_base import AIBase

class ResourceManager(AIModule):

    def __init__(self, ai: AIBase, bases: Iterable[Base]) -> None:
        super().__init__(ai)
        self.bases = ResourceGroup(ai, list(bases))
        self.vespene_geysers: ResourceGroup[VespeneGeyser] = ResourceGroup(self, [g for b in self.bases for g in b.vespene_geysers])
        self.mineral_patches: ResourceGroup[MineralPatch] = ResourceGroup(self, [m for b in self.bases for m in b.mineral_patches])
        self.harvesters_by_resource: Dict[int, Set[GatherBehavior]] = {}
        # self.bases[0].split_initial_workers(set(ai.workers))

    def add_harvester(self, harvester: GatherBehavior) -> None:

        target = next((
            r
            for r in self.bases.flatten()
            if len(self.harvesters_by_resource.get(r, set())) < r.harvester_target), None)

        harvester.target = target

    async def on_step(self) -> None:

        self.bases.update()
        self.mineral_patches.update()
        self.vespene_geysers.update()

        harvesters_by_resource: DefaultDict[ResourceBase, Set[GatherBehavior]] = defaultdict(set)
        for unit in self.ai.unit_manager.behaviors.values():
            if isinstance(unit, GatherBehavior):
                if unit.target:
                    harvesters_by_resource[unit.target].add(unit)
        self.harvesters_by_resource = dict(harvesters_by_resource)