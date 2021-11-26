
from typing import Set, Union, Iterable, Optional

from sc2.position import Point2
from sc2.ids.ability_id import AbilityId
from suntzu.constants import RICH_MINERALS

from .resource_base import ResourceBase
from .resource_single import ResourceSingle

class MineralPatch(ResourceSingle):

    def __init__(self, position: Point2):
        super().__init__(position)
        self.is_rich = False
        self.speed_mining_enabled = False
        self.speed_mining_position: Optional[Point2] = None

    @property
    def harvester_target(self):
        if self.remaining:
            return 2
        else:
            return 0

    def update(self, bot):

        super().update(bot)
        
        patch = bot.resource_by_position.get(self.position)

        if not patch:
            self.remaining = 0
        else:
            if patch.is_visible:
                self.remaining = patch.mineral_contents
            else:
                self.remaining = 1000
            self.is_rich = patch.type_id in RICH_MINERALS

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