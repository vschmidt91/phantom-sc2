
from typing import Set, Union, Iterable

from sc2.position import Point2

from ..observation import Observation
from .resource import Resource
from .resource_single import ResourceSingle

class MineralPatch(ResourceSingle):

    def __init__(self, position: Point2):
        super().__init__(position)

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
        elif patch.is_visible:
            self.remaining = patch.mineral_contents
        else:
            self.remaining = 1000

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