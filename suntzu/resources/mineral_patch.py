
from typing import Set, Union, Iterable

from sc2.position import Point2
from suntzu.constants import RICH_MINERALS

from ..observation import Observation
from .resource import Resource
from .resource_single import ResourceSingle

class MineralPatch(ResourceSingle):

    def __init__(self, position: Point2):
        super().__init__(position)
        self.is_rich = False

    @property
    def harvester_target(self):
        if self.remaining:
            return 2
        else:
            return 0

    def update(self, observation: Observation):

        super().update(observation)

        # self.harvesters = { h for h in self.harvesters if h in observation.unit_by_tag }
        
        patch = observation.resource_by_position.get(self.position)

        if not patch:
            self.remaining = 0
            return

        if patch.is_visible:
            self.remaining = patch.mineral_contents
        else:
            self.remaining = 1000

        self.is_rich = patch.type_id in RICH_MINERALS

        for harvester_tag in self.harvester_set:
            harvester = observation.unit_by_tag.get(harvester_tag)
            if not harvester:
                continue
            elif harvester.is_carrying_resource:
                if not harvester.is_returning:
                    harvester.return_resource()
            elif harvester.is_returning:
                pass
            elif harvester.is_gathering:
                if harvester.order_target != patch.tag:
                    harvester.gather(patch)
            else:
                harvester.gather(patch)

    @property
    def income(self):
        income_per_trip = 7 if self.is_rich else 5
        if not self.remaining:
            return 0
        elif self.harvester_count == 0:
            return 0
        elif self.harvester_count == 1:
            return income_per_trip * 11 / 60
        elif self.harvester_count == 2:
            return income_per_trip * 22 / 60
        else:
            return income_per_trip * 29 / 60