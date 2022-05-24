
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

from sc2.data import race_townhalls
from sc2.position import Point2
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from sc2.units import Units
from src.units.structure import Structure
from ..utils import dot

from ..behaviors.gather import GatherBehavior
from .mineral_patch import MineralPatch
from .vespene_geyser import VespeneGeyser
from .resource_base import ResourceBase
from .resource_group import ResourceGroup

from ..ai_component import AIComponent
if TYPE_CHECKING:
    from ..ai_base import AIBase

class Base(ResourceGroup[ResourceBase]):

    def __init__(self,
        ai: AIBase,
        position: Point2,
        mineral_patches: Iterable[MineralPatch],
        vespene_geysers: Iterable[VespeneGeyser],
    ):
        self.townhall: Optional[Structure] = None
        self.mineral_patches: ResourceGroup[MineralPatch] = ResourceGroup(
            ai,
            sorted(
                mineral_patches,
                key = lambda m : m.position.distance_to(position)
            ))
        self.vespene_geysers: ResourceGroup[VespeneGeyser] = ResourceGroup(
            ai,
            sorted(
                vespene_geysers,
                key = lambda g : g.position.distance_to(position)
            ))
        super().__init__(ai, [self.mineral_patches, self.vespene_geysers], position)

    def split_initial_workers(self, harvesters: Iterable[GatherBehavior]):
        harvesters = set(harvesters)
        for _ in range(len(harvesters)):
            for patch in self.mineral_patches:
                harvester = min(
                    harvesters,
                    key = lambda h : h.unit.position.distance_to(patch.unit.position),
                    default = None
                )
                if not harvester:
                    return
                harvesters.remove(harvester)
                harvester.set_gather_target(patch)