from abc import ABC
from typing import Iterable

import numpy as np
from ares import AresBot
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit

from .constants import RANGE_UPGRADES
from .cost import Cost
from .resources.base import Base
from .resources.mineral_patch import MineralPatch
from .resources.vespene_geyser import VespeneGeyser


class BotBase(AresBot, ABC):

    @property
    def income(self) -> Cost:

        larva_per_second = 0.0
        for hatchery in self.townhalls:
            if hatchery.is_ready:
                larva_per_second += 1 / 11
                if hatchery.has_buff(BuffId.QUEENSPAWNLARVATIMER):
                    larva_per_second += 3 / 29

        return Cost(
            self.state.score.collection_rate_minerals,
            self.state.score.collection_rate_vespene,
            0.0,
            60.0 * larva_per_second,
        )

    def enumerate_positions(self, structure: Unit) -> Iterable[Point2]:
        radius = structure.footprint_radius
        return (
            structure.position + Point2((x_offset, y_offset))
            for x_offset in np.arange(-radius, +radius + 1)
            for y_offset in np.arange(-radius, +radius + 1)
        )

    async def initialize_bases(self):

        base_distances = await self.client.query_pathings(
            [[self.start_location, b] for b in self.expansion_locations_list]
        )
        distance_of_base = {b: d for b, d in zip(self.expansion_locations_list, base_distances)}
        distance_of_base[self.start_location] = 0
        for b in self.enemy_start_locations:
            distance_of_base[b] = np.inf

        start_bases = {self.start_location, *self.enemy_start_locations}

        bases = []
        for position, resources in self.expansion_locations_dict.items():
            if position not in start_bases and not await self.can_place_single(UnitTypeId.HATCHERY, position):
                continue
            base = Base(
                position,
                (MineralPatch(m) for m in resources.mineral_field),
                (VespeneGeyser(g) for g in resources.vespene_geyser),
            )
            bases.append(base)

        bases = sorted(
            bases,
            key=lambda b: distance_of_base[b.position],
        )

        return bases

    def get_unit_range(self, unit: Unit, ground: bool = True, air: bool = True) -> float:
        unit_range = 0.0
        if ground:
            unit_range = max(unit_range, unit.ground_range)
        if air:
            unit_range = max(unit_range, unit.air_range)

        if unit.is_mine and (boni := RANGE_UPGRADES.get(unit.type_id)):
            for upgrade, bonus in boni.items():
                if upgrade in self.state.upgrades:
                    unit_range += bonus

        return unit_range

    def can_move(self, unit: Unit) -> bool:
        if unit.is_burrowed:
            if unit.type_id == UnitTypeId.INFESTORBURROWED:
                return True
            elif unit.type_id == UnitTypeId.ROACHBURROWED:
                return UpgradeId.TUNNELINGCLAWS in self.state.upgrades
            return False
        return 0 < unit.movement_speed

    def can_attack(self, unit: Unit, target: Unit) -> bool:
        if target.is_cloaked and not target.is_revealed:
            return False
        elif target.is_burrowed and not any(self.units_detecting(target)):
            return False
        elif target.is_flying:
            return unit.can_attack_air
        else:
            return unit.can_attack_ground
