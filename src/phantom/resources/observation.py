from dataclasses import dataclass
from functools import cached_property
from typing import TypeAlias

from loguru import logger
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from phantom.common.assignment import Assignment
from phantom.observation import Observation
from phantom.resources.utils import remaining

HarvesterAssignment: TypeAlias = Assignment[int, Point2]


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
        return hash((
            frozenset(self.harvesters),
            frozenset(self.gas_buildings),
            frozenset(self.mineral_fields),
            self.gas_ratio,
        ))

    @cached_property
    def resource_at(self) -> dict[Point2, Unit]:
        return self.mineral_field_at | self.gas_building_at

    @cached_property
    def mineral_field_at(self) -> dict[Point2, Unit]:
        return {r.position: r for r in self.mineral_fields}

    @cached_property
    def gas_building_at(self) -> dict[Point2, Unit]:
        return {g.position: g for g in self.gas_buildings}

    @cached_property
    def vespene_geyser_at(self) -> dict[Point2, Unit]:
        return {g.position: g for g in self.vespene_geysers}

    # cache
    def harvester_target_at(self, p: Point2) -> int:
        if geyser := self.vespene_geyser_at.get(p):
            if remaining(geyser):
                if gas_building := self.gas_building_at.get(p):
                    if gas_building.is_ready:
                        return 2
            return 0
        elif patch := self.mineral_field_at.get(p):
            if not remaining(patch):
                return 0
            return 2
        logger.error(f"Missing resource at {p}")
        return 0
