import math
import re
from abc import ABC, abstractmethod
from collections import defaultdict
from functools import cache, cached_property
from itertools import chain
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
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.common.constants import (
    DPS_OVERRIDE,
    ITEM_BY_ABILITY,
    MICRO_MAP_REGEX,
    MINING_RADIUS,
    RANGE_UPGRADES,
    REQUIREMENTS_KEYS,
    SUPPLY_PROVIDED,
    WITH_TECH_EQUIVALENTS,
    WORKERS,
    ZERG_ARMOR_UPGRADES,
    ZERG_FLYER_ARMOR_UPGRADES,
    ZERG_FLYER_UPGRADES,
    ZERG_MELEE_UPGRADES,
    ZERG_RANGED_UPGRADES,
)
from bot.common.cost import Cost, CostManager
from bot.common.utils import center, get_intersections, project_point_onto_line
from bot.parameter.constants import PARAM_MINERAL_WEIGHT, PARAM_VESPENE_WEIGHT

MacroId: TypeAlias = UnitTypeId | UpgradeId


class BotBase(AresBot, ABC):

    cost: CostManager
    actual_by_type = defaultdict[MacroId, list[Unit]](list)
    pending_by_type = defaultdict[MacroId, list[Unit]](list)
    speedmining_positions = dict[Point2, Point2]()

    def __init__(self, parameters: dict[str, float], game_step_override: int | None = None) -> None:
        super().__init__(game_step_override=game_step_override)
        self.parameters = parameters
        self.cost = CostManager(self.calculate_cost, self.calculate_supply_cost)

    @abstractmethod
    def planned_by_type(self, item: MacroId) -> Iterable:
        raise NotImplementedError()

    @property
    def mineral_weight(self) -> float:
        return math.exp(self.parameters[PARAM_MINERAL_WEIGHT])

    @property
    def vespene_weight(self) -> float:
        return math.exp(self.parameters[PARAM_VESPENE_WEIGHT])

    @cache
    def dps_fast(self, unit: UnitTypeId) -> float:
        if dps := DPS_OVERRIDE.get(unit):
            return dps
        elif units := self.all_units(unit):
            return max(units[0].ground_dps, units[0].air_dps)
        else:
            return 0.0

    @property
    def townhall_at(self) -> dict[Point2, Unit]:
        return {b.position: b for b in self.townhalls}

    @property
    def all_taken_resources(self) -> Units:
        return Units(
            chain.from_iterable(
                rs for p, rs in self.expansion_locations_dict.items() if (th := self.townhall_at.get(p)) and th.is_ready
            ),
            self,
        )

    @cache
    def in_mineral_line(self, base: Point2) -> Point2:
        if not (minerals := self.expansion_locations_dict[base].mineral_field):
            return base
        return center(m.position for m in minerals)

    @cache
    def behind_mineral_line(self, base: Point2) -> Point2:
        return base.towards(self.in_mineral_line(base), 10.0)

    @property
    def bases_taken(self) -> set[Point2]:
        return {b for b in self.expansion_locations_list if (th := self.townhall_at.get(b)) and th.is_ready}

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

        larva_per_second = sum(
            sum(
                (
                    1 / 11 if h.is_ready else 0.0,
                    3 / 29 if h.has_buff(BuffId.QUEENSPAWNLARVATIMER) else 0.0,  # TODO: track actual injects
                )
            )
            for h in self.townhalls
        )

        return Cost(
            self.state.score.collection_rate_minerals / 60.0,  # TODO: get from harvest assignment
            self.state.score.collection_rate_vespene / 60.0,  # TODO: get from harvest assignment
            self.supply_income,  # TODO: iterate over pending
            larva_per_second,
        )

    async def on_start(self) -> None:
        await super().on_start()
        if not self.is_micro_map:
            self.set_speedmining_positions()

    @cached_property
    def is_micro_map(self):
        return re.match(MICRO_MAP_REGEX, self.game_info.map_name)

    def set_speedmining_positions(self) -> None:
        for pos, resources in self.expansion_locations_dict.items():
            for patch in resources.mineral_field:
                target = patch.position.towards(pos, MINING_RADIUS)
                for patch2 in resources.mineral_field:
                    if patch.position == patch2.position:
                        continue
                    position = project_point_onto_line(target, target - pos, patch2.position)
                    distance1 = patch.position.distance_to(pos)
                    distance2 = patch2.position.distance_to(pos)
                    if distance1 < distance2:
                        continue
                    if MINING_RADIUS <= patch2.position.distance_to(position):
                        continue
                    intersections = list(
                        get_intersections(patch.position, MINING_RADIUS, patch2.position, MINING_RADIUS)
                    )
                    if intersections:
                        intersection1, intersection2 = intersections
                        if intersection1.distance_to(pos) < intersection2.distance_to(pos):
                            target = intersection1
                        else:
                            target = intersection2
                        break
                self.speedmining_positions[patch.position] = target

    async def on_step(self, iteration: int):
        await super().on_step(iteration)
        self.update_tables()

    async def initialize_bases(self) -> list[Point2]:

        bs = self.expansion_locations_list
        base_distances = await self.client.query_pathings([[self.start_location, b] for b in bs])
        distance_of_base = dict(zip(bs, base_distances))
        distance_of_base[self.start_location] = 0
        for b in self.enemy_start_locations:
            distance_of_base[b] = np.inf

        start_bases = {self.start_location, *self.enemy_start_locations}
        bases = []
        for position, resources in self.expansion_locations_dict.items():
            if position not in start_bases and not await self.can_place_single(UnitTypeId.HATCHERY, position):
                continue
            bases.append(position)

        bases.sort(key=lambda b: distance_of_base[b.position])
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

    @cache
    def build_time(self, unit_type: UnitTypeId) -> float:
        return self.game_data.units[unit_type.value].cost.time

    @property
    def bank(self) -> Cost:
        return Cost(self.minerals, self.vespene, self.supply_left, self.larva.amount)

    @property
    def supply_income(self) -> float:
        return sum(
            len(self.pending_by_type[unit_type]) * provided / self.build_time(unit_type)
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

    def upgrades_by_unit(self, unit: UnitTypeId) -> Iterable[UpgradeId]:
        if unit == UnitTypeId.ZERGLING:
            return chain(
                (UpgradeId.ZERGLINGMOVEMENTSPEED,),
                # (UpgradeId.ZERGLINGMOVEMENTSPEED, UpgradeId.ZERGLINGATTACKSPEED),
                # self.upgrade_sequence(ZERG_MELEE_UPGRADES),
                # self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.ULTRALISK:
            return chain(
                (UpgradeId.CHITINOUSPLATING, UpgradeId.ANABOLICSYNTHESIS),
                self.upgrade_sequence(ZERG_MELEE_UPGRADES),
                self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.BANELING:
            return chain(
                (UpgradeId.CENTRIFICALHOOKS,),
                self.upgrade_sequence(ZERG_MELEE_UPGRADES),
                self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.ROACH:
            return chain(
                (UpgradeId.GLIALRECONSTITUTION, UpgradeId.BURROW, UpgradeId.TUNNELINGCLAWS),
                # (UpgradeId.GLIALRECONSTITUTION,),
                self.upgrade_sequence(ZERG_RANGED_UPGRADES),
                self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.HYDRALISK:
            return chain(
                (UpgradeId.EVOLVEGROOVEDSPINES, UpgradeId.EVOLVEMUSCULARAUGMENTS),
                self.upgrade_sequence(ZERG_RANGED_UPGRADES),
                self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.QUEEN:
            return chain(
                # self.upgradeSequence(ZERG_RANGED_UPGRADES),
                # self.upgradeSequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.MUTALISK:
            return chain(
                self.upgrade_sequence(ZERG_FLYER_UPGRADES),
                self.upgrade_sequence(ZERG_FLYER_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.CORRUPTOR:
            return chain(
                self.upgrade_sequence(ZERG_FLYER_UPGRADES),
                self.upgrade_sequence(ZERG_FLYER_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.BROODLORD:
            return chain(
                self.upgrade_sequence(ZERG_FLYER_ARMOR_UPGRADES),
                self.upgrade_sequence(ZERG_MELEE_UPGRADES),
                self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.OVERSEER:
            return (UpgradeId.OVERLORDSPEED,)
        else:
            return []

    def upgrade_sequence(self, upgrades) -> Iterable[UpgradeId]:
        for upgrade in upgrades:
            if not self.count(upgrade, include_planned=False):
                return (upgrade,)
        return ()
