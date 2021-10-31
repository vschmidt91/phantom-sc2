
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
from suntzu.resource import Resource

class ResourceGroup(object):

    def __init__(self, resources: Iterable[Resource]):
        self.resources: List[Resource] = list(resources)

    def do_worker_split(self, harvesters: List[Unit]):
        while self.harvester_count < len(harvesters):
            for resource in self.resources:
                harvesters_unassigned = [
                    h for h in harvesters
                    if h.tag not in self.harvesters
                ]
                if not harvesters_unassigned:
                    break
                harvester = min(
                    (h for h in harvesters_unassigned),
                    key=lambda h:h.distance_to(resource.position)
                )
                resource.harvesters.add(harvester.tag)

    def add_harvester(self, harvester: int) -> bool:
        resource = next(
            (r for r in self.resources if 0 < r.remaining and r.harvester_balance < 0),
            None
        ) or min(
            (r for r in self.resources if 0 < r.remaining),
            key=lambda m : m.harvester_balance,
            default=None
        )
        if not resource:
            return False
        resource.harvesters.add(harvester)
        return True

    def request_harvester(self) -> Optional[int]:
        resource = next((r for r in self.resources[::-1] if r.harvester_count and 0 < r.harvester_balance), None)
        if not resource:
            resource = next((r for r in self.resources[::-1] if r.harvester_count), None)
        if not resource:
            return None
        return resource.harvesters.pop()

    def remove_harvester(self, harvester: int) -> bool:
        for resource in self.resources:
            if harvester in resource.harvesters:
                resource.harvesters.remove(harvester)
                return True
        return False

    def try_transfer_to(self, other) -> bool:
        harvester = self.request_harvester()
        if not harvester:
            return False
        if other.add_harvester(harvester):
            return True
        if self.add_harvester(harvester):
            return False
        raise Exception()

    @property
    def harvesters(self) -> Iterable[int]:
        return (h for r in self.resources for h in r.harvesters)

    @property
    def harvester_count(self) -> int:
        return sum(1 for h in self.harvesters)

    @property
    def harvester_target(self) -> int:
        return sum(r.harvester_target for r in self.resources)

    @property
    def harvester_balance(self) -> int:
        return sum(r.harvester_balance for r in self.resources)

    def update(self, observation: Observation):

        for resource in self.resources:
            resource.update(observation)

        while True:
            resource_from = max(self.resources, key=lambda r:r.harvester_balance)
            resource_to = min(self.resources, key=lambda r:r.harvester_balance)
            if resource_from.harvester_count == 0:
                break
            if resource_from.harvester_balance - 1 <= resource_to.harvester_balance + 1:
                break
            resource_to.harvesters.add(resource_from.harvesters.pop())