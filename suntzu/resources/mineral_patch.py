
from typing import Set, Union, Iterable, Optional

from sc2.position import Point2
from sc2.ids.ability_id import AbilityId
from suntzu.constants import RICH_MINERALS

from ..observation import Observation
from .resource import Resource
from .resource_single import ResourceSingle

def speed_mine(harvester, target):
    move_target = target.position.towards(harvester, target.radius + harvester.radius)
    if 0.75 < harvester.distance_to(move_target) < 2:
        harvester.move(move_target)
        harvester(AbilityId.SMART, target, True)

class MineralPatch(ResourceSingle):

    def __init__(self, position: Point2):
        super().__init__(position)
        self.is_rich = False
        self.townhall: Optional[int] = None
        self.speed_mining_enabled = False
        self.speed_mining_position: Option[Point2] = None

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

        townhall = observation.unit_by_tag.get(self.townhall)

        for harvester_tag in self.harvester_set:
            harvester = observation.unit_by_tag.get(harvester_tag)
            if not harvester:
                continue
            
            if self.speed_mining_enabled and townhall and self.harvester_count <= 2:
                
                if harvester.is_gathering and harvester.order_target != patch.tag:
                    harvester(AbilityId.SMART, patch)
                elif harvester.is_idle:
                    harvester(AbilityId.SMART, patch)
                elif len(harvester.orders) == 1:
                    if harvester.is_returning:
                        target = townhall
                        move_target = None
                    else:
                        target = patch
                        move_target = self.speed_mining_position
                    move_target = move_target or target.position.towards(harvester, target.radius + harvester.radius)
                        
                    if 0.75 < harvester.distance_to(move_target) < 2:
                        harvester.move(move_target)
                        harvester(AbilityId.SMART, target, True)


                # elif len(harvester.orders) == 1:
                #     if harvester.is_returning:
                #         move_target = townhall.position.towards(harvester, townhall.radius + harvester.radius)
                #         target = townhall
                #     else:
                #         move_target = patch.position.towards(harvester, patch.radius + harvester.radius)
                #         target = patch
                #     if 0.75 < harvester.distance_to(move_target) < 2:
                #         harvester.move(move_target)
                #         harvester(AbilityId.SMART, target, True)

            else:
                    
                if harvester.is_carrying_resource:
                    if not harvester.is_returning:
                        harvester.return_resource()
                elif harvester.is_returning:
                    pass
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