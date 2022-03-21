
from __future__ import annotations
from typing import Optional, Set, TYPE_CHECKING

from sc2.position import Point2
from sc2.constants import ALL_GAS
from ..constants import RICH_GAS

from .resource_single import ResourceSingle
from .resource_base import ResourceBase
if TYPE_CHECKING:
    from ..ai_base import AIBase

class VespeneGeyser(ResourceSingle):

    def __init__(self, ai: AIBase, position: Point2, base_position: Point2) -> None:
        super().__init__(ai, position, base_position)
        self.is_rich = False

    @property
    def harvester_target(self) -> int:
        if self.base_position not in self.ai.townhall_by_position:
            return 0
        elif self.remaining:
            return 3
        else:
            return 0

    def update(self) -> None:

        super().update()

        geyser = self.ai.resource_by_position.get(self.position)
        self.is_rich = geyser.type_id in RICH_GAS
        building = self.ai.gas_building_by_position.get(self.position)

        if building and building.is_ready:
            self.remaining = building.vespene_contents
        else:
            self.remaining = 0


    @property
    def income(self) -> float:
        if not self.remaining:
            return 0
        vespene_per_trip = 8 if self.is_rich else 4
        if self.harvester_count <= 2:
            trips_per_second = self.harvester_count * 22.4 / 81.0
        else:
            trips_per_second = 22.4 / 33.0
        vespene_per_second = vespene_per_trip * trips_per_second
        return vespene_per_second