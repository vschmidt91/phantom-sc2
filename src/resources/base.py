
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

# def get_intersections(p0: Point2, r0: float, p1: Point2, r1: float) -> List[Point2]:
#     return _get_intersections(p0.x, p0.y, r0, p1.x, p1.y, r1)


def _get_intersections(x0: float, y0: float, r0: float, x1: float, y1: float, r1: float) -> List[Point2]:
    # circle 1: (x0, y0), radius r0
    # circle 2: (x1, y1), radius r1

    d = math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2)

    # non intersecting
    if d > r0 + r1:
        return []
    # One circle within other
    if d < abs(r0 - r1):
        return []
    # coincident circles
    if d == 0 and r0 == r1:
        return []
    else:
        a = (r0 ** 2 - r1 ** 2 + d ** 2) / (2 * d)
        h = math.sqrt(r0 ** 2 - a ** 2)
        x2 = x0 + a * (x1 - x0) / d
        y2 = y0 + a * (y1 - y0) / d
        x3 = x2 + h * (y1 - y0) / d
        y3 = y2 - h * (x1 - x0) / d

        x4 = x2 - h * (y1 - y0) / d
        y4 = y2 + h * (x1 - x0) / d

        return [Point2((x3, y3)), Point2((x4, y4))]

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
                (MineralPatch(ai, m) for m in minerals),
                key = lambda m : m.position.distance_to(townhall_position)
            ))
        self.vespene_geysers: ResourceGroup[VespeneGeyser] = ResourceGroup(
            ai,
            sorted(
                (VespeneGeyser(ai, g) for g in gasses),
                key = lambda g : g.position.distance_to(townhall_position)
            ))
        self.mineral_patches.balancing_mode = BalancingMode.MINIMIZE_TRANSFERS
        self.vespene_geysers.balancing_mode = BalancingMode.NONE
        super().__init__(ai, [self.mineral_patches, self.vespene_geysers], townhall_position)
        self.blocked_since: Optional[float] = None
        self.taken_since: Optional[float] = None
        self.balancing_mode = BalancingMode.NONE
        self.defensive_units: List[Unit] = list()
        self.defensive_units_planned: List[MacroPlan] = list()
        self.defensive_targets: DefaultDict[UnitTypeId, int] = DefaultDict(lambda:0)
        self.fix_speedmining_positions()
        self.townhall: Optional[Unit] = None

        self.vespene_switching_state: Dict[int, bool] = dict()
        # if 2 <= len(self.vespene_geysers):
        #     geyser_distance = self.vespene_geysers[0].position.distance_to(self.vespene_geysers[1].position)
        #     if geyser_distance < 10:
        #         self.vespene_switching_enabled = True

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
                        plan.target = self.position.towards(self.mineral_patches.position, 4.5)
                    elif unit_type == UnitTypeId.SPINECRAWLER:
                        plan.target = self.position.towards(self.mineral_patches.position, -5)
                    else:
                        plan.target = self.position
                    plan.target = plan.target.rounded.offset((.5, .5))
                    plan.max_distance = 2
                    plan.priority = 0
                    self.ai.add_macro_plan(plan)

        super().update()

        if self.vespene_switching_enabled:

            for tag in self.harvesters:
                unit = self.ai.unit_by_tag.get(tag)
                if not unit:
                    continue
                state = self.vespene_switching_state.setdefault(tag, False)
                if state and not unit.is_carrying_vespene:
                    if tag in self.vespene_geysers[0].harvesters:
                        i = 0
                        j = 1
                    else:
                        i = 1
                        j = 0
                    assert self.vespene_geysers[i].try_remove(tag)
                    assert self.vespene_geysers[j].try_add(tag)
                    self.vespene_switching_state[tag] = False
                elif not state and unit.is_carrying_vespene:
                    self.vespene_switching_state[tag] = True
