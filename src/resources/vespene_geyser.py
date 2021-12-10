
from typing import Optional, Set

from sc2.position import Point2
from sc2.constants import ALL_GAS
from ..constants import RICH_GAS

from .resource_single import ResourceSingle
from .resource_base import ResourceBase

class VespeneGeyser(ResourceSingle):

    def __init__(self, position: Point2):
        super().__init__(position)
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
        self.is_rich = geyser.type_id in RICH_GAS
        building = bot.gas_building_by_position.get(self.position)

        if building and building.is_ready:
            self.remaining = building.vespene_contents
        else:
            self.remaining = 0


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