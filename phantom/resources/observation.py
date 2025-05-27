from dataclasses import dataclass
from functools import cached_property

from sc2.unit import Unit
from sc2.units import Units

from phantom.common.utils import Point
from phantom.observation import Observation
from phantom.resources.utils import remaining

HarvesterAssignment = dict[int, Point]


@dataclass(frozen=True)
class ResourceObservation:
    observation: Observation
    harvesters: Units
    gas_buildings: Units
    vespene_geysers: Units
    mineral_fields: Units
    gas_ratio: float

    @cached_property
    def gather_hash(self) -> int:
        return hash(
            (
                frozenset(self.harvesters),
                frozenset(self.gas_buildings),
                frozenset(self.mineral_fields),
                self.gas_ratio,
            )
        )

    @cached_property
    def resource_at(self) -> dict[Point, Unit]:
        return self.mineral_field_at | self.gas_building_at

    @cached_property
    def mineral_field_at(self) -> dict[Point, Unit]:
        return {tuple(r.position.rounded): r for r in self.mineral_fields}

    @cached_property
    def gas_building_at(self) -> dict[Point, Unit]:
        return {tuple(g.position.rounded): g for g in self.gas_buildings}

    @cached_property
    def vespene_geyser_at(self) -> dict[Point, Unit]:
        return {tuple(g.position.rounded): g for g in self.vespene_geysers}

    # cache
    def harvester_target_of_gas(self, resource: Unit) -> int:
        if resource.mineral_contents == 0:
            if not resource.is_ready:
                return 0
            p = tuple(resource.position.rounded)
            if not (geyser := self.vespene_geyser_at.get(p)):
                return 0
            if not remaining(geyser):
                return 0
            return 2
        else:  # resource is mineralpatch
            return 2
