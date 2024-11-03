from abc import ABC, abstractmethod
from collections import defaultdict
from functools import lru_cache
from typing import Iterable, TypeAlias

import numpy as np
from ares import AresBot
from sc2.dicts.unit_research_abilities import RESEARCH_INFO
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.unit import Unit

from .constants import (
    DPS_OVERRIDE,
    ITEM_BY_ABILITY,
    RANGE_UPGRADES,
    REQUIREMENTS_KEYS,
    SUPPLY_PROVIDED,
    WITH_TECH_EQUIVALENTS,
    WORKERS,
)
from .cost import Cost, CostManager
from .resources.expansion import Expansion

MacroId: TypeAlias = UnitTypeId | UpgradeId


class BotBase(AresBot, ABC):

    bases = list[Expansion]()
    cost: CostManager
    actual_by_type: defaultdict[MacroId, list[Unit]] = defaultdict(list)
    pending_by_type: defaultdict[MacroId, list[Unit]] = defaultdict(list)

    def __init__(self, game_step_override: int | None = None) -> None:
        super().__init__(game_step_override=game_step_override)
        self.cost = CostManager(self.calculate_cost, self.calculate_supply_cost)

    @property
    def ai(self):
        return self

    @abstractmethod
    def planned_by_type(self, item: MacroId) -> Iterable:
        raise NotImplementedError()

    @lru_cache(maxsize=None)
    def dps_fast(self, unit: UnitTypeId) -> float:
        if dps := DPS_OVERRIDE.get(unit):
            return dps
        elif units := self.all_units(unit):
            return max(units[0].ground_dps, units[0].air_dps)
        else:
            return 0.0

    def count(
        self, item: MacroId, include_pending: bool = True, include_planned: bool = True, include_actual: bool = True
    ) -> int:
        factor = 2 if item == UnitTypeId.ZERGLING else 1

        count = 0
        if include_actual:
            if item in WORKERS:
                count += self.supply_workers
            else:
                count += len(self.actual_by_type[item])
        if include_pending:
            count += factor * len(self.pending_by_type[item])
        if include_planned:
            count += factor * sum(1 for _ in self.planned_by_type(item))

        return count

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

    async def on_start(self) -> None:
        await super().on_start()
        self.bases = await self.initialize_bases()

    async def on_step(self, iteration: int):
        await super().on_step(iteration)
        self.update_tables()

    async def initialize_bases(self) -> list[Expansion]:

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
            base = Expansion(position, resources)
            bases.append(base)

        bases = sorted(
            bases,
            key=lambda b: distance_of_base[b.position],
        )

        return bases

    def update_tables(self):
        self.actual_by_type.clear()
        self.pending_by_type.clear()

        for unit in self.all_own_units:
            if unit.is_ready:
                self.actual_by_type[unit.type_id].append(unit)
                for order in unit.orders:
                    if item := ITEM_BY_ABILITY.get(order.ability.exact_id):
                        self.pending_by_type[item].append(unit)
            else:
                self.pending_by_type[unit.type_id].append(unit)

        for upgrade in self.state.upgrades:
            self.actual_by_type[upgrade] = [self.all_units[0]]

    def is_unit_missing(self, unit: UnitTypeId) -> bool:
        if unit in {
            UnitTypeId.LARVA,
            # UnitTypeId.CORRUPTOR,
            # UnitTypeId.ROACH,
            # UnitTypeId.HYDRALISK,
            # UnitTypeId.ZERGLING,
        }:
            return False
        return all(
            self.count(e, include_pending=False, include_planned=False) == 0 for e in WITH_TECH_EQUIVALENTS[unit]
        )

    @property
    def supply_pending(self) -> int:
        return sum(
            provided * len(self.pending_by_type[unit_type])
            for unit_type, provided in SUPPLY_PROVIDED[self.race].items()
        )

    @property
    def supply_planned(self) -> int:
        return sum(
            provided
            for unit_type, provided in SUPPLY_PROVIDED[self.race].items()
            for _ in self.planned_by_type(unit_type)
        )

    def get_missing_requirements(self, item: MacroId) -> Iterable[MacroId]:
        if item not in REQUIREMENTS_KEYS:
            return

        if isinstance(item, UnitTypeId):
            trainers = UNIT_TRAINED_FROM[item]
            trainer = min(trainers, key=lambda v: v.value)
            info = TRAIN_INFO[trainer][item]
        elif isinstance(item, UpgradeId):
            trainer = UPGRADE_RESEARCHED_FROM[item]
            info = RESEARCH_INFO[trainer][item]
        else:
            raise ValueError(item)

        if self.is_unit_missing(trainer):
            yield trainer
        if (required_building := info.get("required_building")) and self.is_unit_missing(required_building):
            yield required_building
        if (
            (required_upgrade := info.get("required_upgrade"))
            and isinstance(required_upgrade, UpgradeId)
            and required_upgrade not in self.state.upgrades
        ):
            yield required_upgrade

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
