from collections.abc import Mapping

from sc2.unit import Unit
from sc2.units import Units

from phantom.common.utils import Point
from phantom.observation import Observation
from phantom.resources.utils import remaining

HarvesterAssignment = dict[int, Point]


class ResourceObservation:
    def __init__(
        self,
        observation: Observation,
        harvesters: Units,
        gas_buildings: Units,
        vespene_geysers: Units,
        mineral_fields: Units,
        gas_ratio: float,
        workers_in_geysers: Mapping[int, Unit],
    ):
        self.observation = observation
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
                observation.researched_speed,
                self.gas_ratio,
            )
        )

        self.mineral_field_at = {tuple(r.position.rounded): r for r in self.mineral_fields}
        self.gas_building_at = {tuple(g.position.rounded): g for g in self.gas_buildings}
        self.vespene_geyser_at = {tuple(g.position.rounded): g for g in self.vespene_geysers}
        self.resource_at = self.mineral_field_at | self.gas_building_at

    def harvester_target_of_gas(self, resource: Unit) -> int:
        if resource.mineral_contents == 0:
            if not resource.is_ready:
                return 0
            p = tuple(resource.position.rounded)
            if not (geyser := self.vespene_geyser_at.get(p)):
                return 0
            if not remaining(geyser):
                return 0
            if not self.observation.researched_speed:
                return 3
            return 2
        else:  # resource is mineralpatch
            return 2
