
from s2clientprotocol.common_pb2 import Point
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

class ResourceGroup(Resource):

    def __init__(self, resources: List[Resource]):
        position = sum((r.position for r in resources), Point2((0, 0))) / sum(1 for r in resources)
        super().__init__(position)
        self.resources: List[Resource] = resources
        self.balance_aggressively: bool = False

    def try_add(self, harvester: int) -> bool:
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
        return resource.try_add(harvester)

    def try_remove_any(self) -> Optional[int]:
        # resource = next((r for r in self.resources[::-1] if 0 < r.harvester_count and 0 < r.harvester_balance), None)
        # if not resource:
        #     resource = next((r for r in self.resources[::-1] if 0 < r.harvester_count), None)
        resource = max(
            (r for r in self.resources if 0 < r.harvester_count),
            key=lambda r:r.harvester_balance,
            default=None
        )
        if not resource:
            return None
        return resource.try_remove_any()

    def try_remove(self, harvester: int) -> bool:
        return any(r.try_remove(harvester) for r in self.resources)

    @property
    def harvesters(self) -> Iterable[int]:
        return (h in r.harvesters for r in self.resources for h in r.harvesters)

    @property
    def harvester_target(self):
        return sum(r.harvester_target for r in self.resources)

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

    @property
    def harvesters(self) -> Iterable[int]:
        return (h for r in self.resources for h in r.harvesters)

    @property
    def harvester_target(self) -> int:
        return sum(r.harvester_target for r in self.resources)

    def update(self, observation: Observation):

        for resource in self.resources:
            resource.update(observation)

        super().update(observation)

        self.remaining = sum(r.remaining for r in self.resources)

        while True:
            resource_from = max(
                (r for r in self.resources if 0 < r.harvester_count),
                key=lambda r:r.harvester_balance,
                default=None
            )
            if not resource_from:
                break
            resource_to = min(self.resources, key=lambda r:r.harvester_balance)
            if self.balance_aggressively:
                if resource_from.harvester_count == 0:
                    break
                if resource_from.harvester_balance - 1 <= resource_to.harvester_balance + 1:
                    break
            else:
                if resource_from.harvester_balance <= 0:
                    break
                if 0 <= resource_to.harvester_balance:
                    break
            # print('transfer internal')
            if not resource_from.try_transfer_to(resource_to):
                print('transfer internal failed')
                break