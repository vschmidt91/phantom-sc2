
from s2clientprotocol.error_pb2 import HarvestersNotRequired
from s2clientprotocol.sc2api_pb2 import Observation
from sc2.position import Point2
from typing import Dict, Iterable, Set, List, Optional
from itertools import chain

from sc2.unit import Unit
from sc2.units import Units
from suntzu import minerals
from suntzu.minerals import Minerals
from suntzu.gas import Gas
from suntzu.resource_group import ResourceGroup

class Base(ResourceGroup):

    def __init__(self,
        townhall_position: Point2,
        minerals: Iterable[Point2],
        gasses: Iterable[Point2],
    ):
        self.minerals: ResourceGroup = ResourceGroup(sorted(
            (Minerals(m) for m in minerals),
            key = lambda m : m.position.distance_to(townhall_position)
        ))
        self.minerals.balance_aggressively = True
        self.gasses: ResourceGroup = ResourceGroup(sorted(
            (Gas(g) for g in gasses),
            key = lambda g : g.position.distance_to(townhall_position)
        ))
        self.minerals.balance_aggressively = True
        self.townhall_position: Point2 = townhall_position
        self.townhall: Optional[int] = None
        self.townhall_ready: bool = False
        super().__init__([self.minerals, self.gasses])

    def update(self, observation: Observation):


        # townhall = observation.unit_by_tag.get(self.townhall)
        # if not townhall:
        #     self.townhall = None
        #     self.townhall_ready = False
        # else:
        #     self.townhall_ready = townhall.is_ready

        super().update(observation)

        if not self.townhall_ready:
            self.remaining = 0