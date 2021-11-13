
from typing import Optional, Set

from sc2.position import Point2
from sc2.constants import ALL_GAS
from suntzu.constants import RICH_GAS

from .resource_single import ResourceSingle
from .resource import Resource

class VespeneGeyser(ResourceSingle):

    def __init__(self, position: Point2):
        super().__init__(position)
        self.building: Optional[int] = None
        self.is_rich = False

    @property
    def harvester_target(self):
        if self.remaining:
            return 3
        else:
            return 0

    def update(self, bot):
        super().update(bot)
        geyser = bot.resource_by_position.get(self.position)
        if not geyser:
            self.remaining = 0
            return

        self.is_rich = geyser.type_id in RICH_GAS

        building = bot.unit_by_tag.get(self.building)
        if not building:
            self.building = None
            gas_buildings = {
                g
                for t in ALL_GAS
                for g in bot.actual_by_type[t]
            }
            building = next(filter(lambda g : g.position == self.position, gas_buildings), None)


        if not (building and building.is_ready):
            self.remaining = 0
            return

        self.building = building.tag

        self.remaining = building.vespene_contents

        if self.building and self.remaining:
            for harvester in (bot.unit_by_tag.get(h) for h in self.harvester_set):
                if not harvester:
                    continue
                elif harvester.is_carrying_resource:
                    if not harvester.is_returning:
                        harvester.return_resource()
                elif harvester.is_returning:
                    pass
                else:
                    harvester.gather(building)

    @property
    def income(self):
        income_per_trip = 8 if self.is_rich else 4
        if not self.remaining:
            return 0
        elif self.harvester_count == 0:
            return 0
        elif self.harvester_count == 1:
            return income_per_trip * 15 / 60
        elif self.harvester_count == 2:
            return income_per_trip * 30 / 60
        else:
            return income_per_trip * 41 / 60