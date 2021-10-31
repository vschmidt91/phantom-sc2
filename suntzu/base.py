
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

class Base(object):

    def __init__(self,
        townhall_position: Point2,
        minerals: Iterable[Minerals],
        gasses: Iterable[Gas],
    ):
        self.townhall_position: Point2 = townhall_position
        self.townhall: Optional[int] = None
        self.townhall_ready: Optional[bool] = None
        self.minerals: ResourceGroup = ResourceGroup(sorted(
            minerals,
            key = lambda m : m.position.distance_to(townhall_position)
        ))
        self.gasses: ResourceGroup = ResourceGroup(sorted(
            gasses,
            key = lambda g : g.position.distance_to(townhall_position)
        ))

    def do_worker_split(self, harvesters: List[Unit]):
        return self.minerals.do_worker_split(harvesters)

    def add_harvester(self, harvester: int) -> bool:
        if self.minerals.harvester_balance < self.gasses.harvester_balance:
            return self.minerals.add_harvester(harvester) or self.gasses.add_harvester(harvester)
        else:
            return self.gasses.add_harvester(harvester) or self.minerals.add_harvester(harvester)

    def request_harvester(self) -> Optional[int]:
        if self.gasses.harvester_balance <= self.minerals.harvester_balance:
            return self.minerals.request_harvester() or self.gasses.request_harvester()
        else:
            return self.gasses.request_harvester() or self.minerals.request_harvester()

    def remove_harvester(self, harvester: int) -> bool:
        return self.minerals.remove_harvester(harvester) or self.gasses.remove_harvester(harvester)

    @property
    def harvesters(self) -> Iterable[int]:
        return chain(self.minerals.harvesters, self.gasses.harvesters)

    @property
    def harvester_balance(self) -> int:
        return self.minerals.harvester_balance + self.gasses.harvester_balance

    def update(self, observation: Observation):

        self.minerals.update(observation)
        self.gasses.update(observation)

        if 0 < self.gasses.harvester_balance:
            self.gasses.try_transfer_to(self.minerals)

        townhall = observation.unit_by_tag.get(self.townhall)
        if not townhall:
            self.townhall = None
            self.townhall_ready = False
        else:
            self.townhall_ready = townhall.is_ready