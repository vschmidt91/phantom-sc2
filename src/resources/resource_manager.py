

from __future__ import annotations
from collections import defaultdict
from typing import TYPE_CHECKING, Counter, DefaultDict, Dict, Iterable, Set
import numpy as np
import math

from sc2.position import Point2
from src.resources.resource_unit import ResourceUnit

from ..utils import dot
from .resource_base import ResourceBase
from .mineral_patch import MineralPatch
from .vespene_geyser import VespeneGeyser
from .base import Base
from ..behaviors.gather import GatherBehavior
from .resource_group import ResourceGroup
from ..modules.module import AIModule
if TYPE_CHECKING:
    from ..ai_base import AIBase

MINING_RADIUS = 1.325
# MINING_RADIUS = 1.4

MINERAL_RADIUS = 1.125
HARVESTER_RADIUS = 0.375

def project_point_onto_line(p: Point2, d: Point2, x: Point2) -> float:
    n = Point2((d[1], -d[0]))
    return x - dot(x - p, n) / dot(n, n) * n

def get_intersections(p0: Point2, r0: float, p1: Point2, r1: float) -> Iterable[Point2]:
    p01 = p1 - p0
    d = np.linalg.norm(p01)
    if 0 < d and abs(r0 - r1) <= d <= r0 + r1:
        a = (r0 ** 2 - r1 ** 2 + d ** 2) / (2 * d)
        h = math.sqrt(r0 ** 2 - a ** 2)
        pm = p0 + (a / d) * p01
        po = (h / d) * np.array([p01.y, -p01.x])
        yield pm + po
        yield pm - po

class ResourceManager(AIModule):

    def __init__(self, ai: AIBase, bases: Iterable[Base]) -> None:
        super().__init__(ai)
        self.do_split = True
        self.bases = ResourceGroup(ai, list(bases))
        self.vespene_geysers: ResourceGroup[VespeneGeyser] = ResourceGroup(self, [g for b in self.bases for g in b.vespene_geysers])
        self.mineral_patches: ResourceGroup[MineralPatch] = ResourceGroup(self, [m for b in self.bases for m in b.mineral_patches])
        self.speedmining_positions = self.get_speedmining_positions()
        self.harvesters_by_resource: Counter[ResourceUnit] = Counter()

    def add_harvester(self, harvester: GatherBehavior) -> None:
        harvester.target = min(self.bases.flatten(), key = lambda r : r.harvester_balance)

    async def on_step(self) -> None:

        if self.do_split:
            harvesters = [self.ai.unit_manager.behaviors[w.tag] for w in self.ai.workers]
            self.bases[0].split_initial_workers(harvesters)
            self.do_split = False

        self.mineral_patches.update()
        self.vespene_geysers.update()
        self.bases.update()

        self.harvesters_by_resource = Counter(
            (unit.target
            for unit in self.ai.unit_manager.behaviors.values()
            if isinstance(unit, GatherBehavior) and unit.target))

        harvesters = [
            b
            for b in self.ai.unit_manager.behaviors.values()
            if isinstance(b, GatherBehavior) and b.target and isinstance(b.target, MineralPatch)
        ]

        transfer = next((
            h
            for h in harvesters
            if 0 < h.target.harvester_balance
        ), None)
        if transfer:
            transfer_to = next((
                p
                for p in self.mineral_patches
                if p.harvester_balance < 0
            ), None)
            if transfer_to:
                transfer.target = transfer_to

        # if transfer_to.harvester_balance < 0 < transfer.target.harvester_balance:


    def get_speedmining_positions(self) -> Dict[MineralPatch, Point2]:
        positions = dict()
        for base in self.bases:
            for patch in base.mineral_patches:
                target = patch.position.towards(base.position, MINING_RADIUS)
                for patch2 in self.mineral_patches:
                    if patch.position == patch2.position:
                        continue
                    p = project_point_onto_line(target, target - base.position, patch2.position)
                    if patch.position.distance_to(base.position) < patch2.position.distance_to(base.position):
                        continue
                    if MINING_RADIUS <= patch2.position.distance_to(p):
                        continue
                    if target := min(
                        get_intersections(patch.position, MINING_RADIUS, patch2.position, MINING_RADIUS),
                        key = lambda p : p.distance_to(base.position),
                        default = None):
                        break
                positions[patch] = target
        return positions