from collections.abc import Mapping
from typing import TYPE_CHECKING

from sc2.ids.upgrade_id import UpgradeId
from sc2.unit import Unit
from sc2.units import Units

from phantom.common.utils import Point, to_point
from phantom.resources.utils import remaining

if TYPE_CHECKING:
    from phantom.main import PhantomBot

type HarvesterAssignment = dict[int, Point]


class ResourceObservation:
    def __init__(
        self,
        bot: "PhantomBot",
        harvesters: Units,
        gas_buildings: Units,
        vespene_geysers: Units,
        mineral_fields: Units,
        gas_ratio: float,
        workers_in_geysers: Mapping[int, Unit],
    ):
        self.bot = bot
        self.researched_speed = (
            self.bot.count_actual(UpgradeId.ZERGLINGMOVEMENTSPEED)
            + self.bot.count_pending(UpgradeId.ZERGLINGMOVEMENTSPEED)
            > 0
        )
        self.harvesters = harvesters
        self.gas_buildings = gas_buildings
        self.vespene_geysers = vespene_geysers
        self.mineral_fields = mineral_fields
        self.gas_ratio = gas_ratio
        self.workers_in_geysers = workers_in_geysers

        harvester_tags = harvesters.tags | set(workers_in_geysers)
        self.gather_hash = hash(
            (
                frozenset(harvester_tags),
                frozenset(self.gas_buildings),
                frozenset(self.mineral_fields),
                self.researched_speed,
                self.gas_ratio,
            )
        )

        self.mineral_field_at = {to_point(r.position): r for r in self.mineral_fields}
        self.gas_building_at = {to_point(g.position): g for g in self.gas_buildings}
        self.vespene_geyser_at = {to_point(g.position): g for g in self.vespene_geysers}
        self.resource_at = self.mineral_field_at | self.gas_building_at

    def harvester_target_of(self, resource: Unit) -> int:
        if resource.mineral_contents == 0:
            if not resource.is_ready:
                return 0
            p = to_point(resource.position)
            if not (geyser := self.vespene_geyser_at.get(p)):
                return 0
            if not remaining(geyser):
                return 0
            if not self.researched_speed:
                return 3
            return 2
        else:  # resource is mineralpatch
            return 2
