
from __future__ import annotations
import numpy as np
from collections import defaultdict
from email.policy import default
from typing import Counter, DefaultDict, Dict, Iterable, Set, List, Optional, TYPE_CHECKING
from itertools import chain
import math
from matplotlib.pyplot import jet

from s2clientprotocol.sc2api_pb2 import Observation
from sc2.ids.ability_id import AbilityId

from sc2.position import Point2
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from sc2.units import Units
from ..macro_plan import MacroPlan
from ..utils import dot

from .mineral_patch import MineralPatch
from .vespene_geyser import VespeneGeyser
from .resource_base import ResourceBase
from .resource_group import BalancingMode, ResourceGroup

from ..ai_component import AIComponent
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

class Base(ResourceGroup[ResourceBase]):

    def __init__(self,
        ai: AIBase,
        townhall_position: Point2,
        minerals: Iterable[Point2],
        gasses: Iterable[Point2],
    ):
        self.mineral_patches: ResourceGroup[MineralPatch] = ResourceGroup(
            ai,
            sorted(
                (MineralPatch(ai, m, townhall_position) for m in minerals),
                key = lambda m : m.position.distance_to(townhall_position)
            ))
        self.vespene_geysers: ResourceGroup[VespeneGeyser] = ResourceGroup(
            ai,
            sorted(
                (VespeneGeyser(ai, g, townhall_position) for g in gasses),
                key = lambda g : g.position.distance_to(townhall_position)
            ))
        self.mineral_patches.balancing_mode = BalancingMode.MINIMIZE_TRANSFERS
        self.vespene_geysers.balancing_mode = BalancingMode.NONE
        super().__init__(ai, [self.mineral_patches, self.vespene_geysers], townhall_position)
        self.balancing_mode = BalancingMode.NONE
        self.defensive_units: List[Unit] = list()
        self.defensive_units_planned: List[MacroPlan] = list()
        self.defensive_targets: DefaultDict[UnitTypeId, int] = DefaultDict(lambda:0)
        self.fix_speedmining_positions()
        self.townhall: Optional[Unit] = None

    def split_initial_workers(self, harvesters: Set[Unit]):
        for _ in range(len(harvesters)):
            for patch in self.mineral_patches:
                harvester = min(
                    harvesters,
                    key = lambda h : h.position.distance_to(patch.position),
                    default = None
                )
                if not harvester:
                    return
                harvesters.remove(harvester)
                patch.try_add(harvester.tag)

    def fix_speedmining_positions(self):
        for patch in self.mineral_patches:
            target = patch.position.towards(self.position, MINING_RADIUS)
            for patch2 in self.mineral_patches:
                if patch.position == patch2.position:
                    continue
                p = project_point_onto_line(target, target - self.position, patch2.position)
                if patch.position.distance_to(self.position) < p.distance_to(self.position):
                    continue
                if MINING_RADIUS <= patch2.position.distance_to(p):
                    continue
                if target := min(
                    get_intersections(patch.position, MINING_RADIUS, patch2.position, MINING_RADIUS),
                    key = lambda p : p.distance_to(self.position),
                    default = None):
                    break
            patch.speedmining_target = target

    @property
    def harvester_target(self) -> int:
        if not self.townhall:
            return 0
        return super().harvester_target

    def update(self):

        self.townhall = self.ai.townhall_by_position.get(self.position)
        if self.townhall and self.defensive_targets:
            defenses = Counter()
            defenses.update(u.type_id for u in self.defensive_units)
            defenses.update(p.item for p in self.defensive_units_planned)
            for unit_type, want in self.defensive_targets.items():
                if defenses[unit_type] < want:
                    plan = MacroPlan(unit_type)
                    if unit_type == UnitTypeId.SPORECRAWLER:
                        if defenses[unit_type] == 0:
                            plan.target = self.position.towards(self.mineral_patches.position, 4.5)
                        else:
                            plan.target = self.position.towards(self.mineral_patches.position, -6)
                    elif unit_type == UnitTypeId.SPINECRAWLER:
                        plan.target = self.position.towards(self.mineral_patches.position, -5)
                    else:
                        plan.target = self.position
                    plan.target = plan.target.rounded.offset((.5, .5))
                    plan.max_distance = 4
                    plan.priority = 0
                    self.ai.add_macro_plan(plan)

        super().update()