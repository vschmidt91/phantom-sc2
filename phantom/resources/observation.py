from collections.abc import Sequence
from typing import TYPE_CHECKING

from sc2.unit import Unit

from phantom.common.utils import Point, to_point

if TYPE_CHECKING:
    from phantom.main import PhantomBot

type HarvesterAssignment = dict[int, Point]


class ResourceObservation:
    def __init__(
        self,
        bot: "PhantomBot",
        harvesters: Sequence[Unit],
        mineral_fields: Sequence[Unit],
        gas_buildings: Sequence[Unit],
        gas_target: int,
    ):
        self.bot = bot
        self.harvesters = harvesters
        self.mineral_fields = mineral_fields
        self.gas_buildings = gas_buildings
        self.gas_target = gas_target
        self.resources = list[Unit]()
        self.resources.extend(self.mineral_fields)
        self.resources.extend(self.gas_buildings)
        self.resource_by_position = {to_point(r.position): r for r in self.resources}

        self.gather_hash = hash(
            (
                frozenset(harvesters),
                frozenset(self.mineral_fields),
                frozenset(self.gas_buildings),
                self.bot.harvesters_per_gas_building,
                self.gas_target,
            )
        )

        # self.mineral_field_at = {to_point(r.position): r for r in self.mineral_fields}
        # self.gas_building_at = {to_point(g.position): g for g in self.gas_buildings}
        # self.resource_at = self.mineral_field_at | self.gas_building_at
