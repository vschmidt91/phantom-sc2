from collections import defaultdict
from dataclasses import dataclass
from functools import cache, cached_property
from itertools import chain, product
from typing import Iterable

import numpy as np
from ares import UnitTreeQueryType
from sc2.data import Race
from sc2.dicts.unit_research_abilities import RESEARCH_INFO
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.game_data import UnitTypeData
from sc2.game_state import ActionError, ActionRawUnitCommand, EffectData
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2, Point3, Size
from sc2.unit import Unit
from sc2.units import Units

from cython_extensions import cy_center
from phantom.common.constants import (
    CIVILIANS,
    ENEMY_CIVILIANS,
    HALF,
    ITEM_BY_ABILITY,
    MAX_UNIT_RADIUS,
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
from phantom.common.cost import Cost, CostManager
from phantom.common.main import BotBase
from phantom.common.utils import MacroId, Point, center, pairwise_distances
from phantom.knowledge import Knowledge


@dataclass(frozen=True)
class Observation:
    bot: BotBase

    @cached_property
    def workers_in_geysers(self) -> int:
        # TODO: consider dropperlords, nydus, ...
        return int(self.bot.supply_workers) - self.bot.workers.amount

    @cached_property
    def unit_by_tag(self) -> dict[int, Unit]:
        return self.bot.unit_tag_dict

    @property
    def action_errors(self) -> list[ActionError]:
        return self.bot.state.action_errors

    @property
    def map_size(self) -> Size:
        return self.bot.game_info.map_size

    @property
    def supply_workers(self) -> float:
        return self.bot.supply_workers

    @property
    def supply_cap(self) -> float:
        return self.bot.supply_cap

    @property
    def cost(self) -> CostManager:
        return self.bot.cost

    @property
    def researched_speed(self) -> bool:
        return 0.0 < self.bot.already_pending_upgrade(UpgradeId.ZERGLINGMOVEMENTSPEED)

    @property
    def effects(self) -> set[EffectData]:
        return self.bot.state.effects

    @property
    def upgrades(self) -> set[UpgradeId]:
        return self.bot.state.upgrades

    @cached_property
    def actions_unit_commands(self) -> dict[int, ActionRawUnitCommand]:
        return {t: a for a in self.bot.state.actions_unit_commands for t in a.unit_tags}

    @cached_property
    def shootable_targets(self) -> dict[Unit, list[Unit]]:
        units = self.combatants
        base_ranges = [u.radius for u in units]
        # base_ranges = [u.radius + MAX_UNIT_RADIUS for u in units]
        ground_ranges = [b + u.ground_range for u, b in zip(units, base_ranges)]
        air_ranges = [b + u.air_range for u, b in zip(units, base_ranges)]

        ground_candidates = self.bot.mediator.get_units_in_range(
            start_points=units,
            distances=ground_ranges,
            query_tree=UnitTreeQueryType.EnemyGround,
        )
        air_candidates = self.bot.mediator.get_units_in_range(
            start_points=units,
            distances=air_ranges,
            query_tree=UnitTreeQueryType.EnemyFlying,
        )
        targets = {
            u: list(filter(u.target_in_range, a | b)) for u, a, b in zip(units, ground_candidates, air_candidates)
        }
        return targets

    @property
    def units(self) -> Units:
        return self.bot.all_own_units

    @property
    def combatants(self) -> Units:
        if self.bot.is_micro_map:
            return self.bot.units
        else:
            return self.bot.units.exclude_type(CIVILIANS)

    @property
    def overseers(self) -> Units:
        return self.bot.units({UnitTypeId.OVERSEER, UnitTypeId.OVERSEERSIEGEMODE})

    @property
    def enemy_units(self) -> Units:
        return self.bot.all_enemy_units

    @property
    def enemy_combatants(self) -> Units:
        if self.bot.is_micro_map:
            return self.bot.enemy_units
        else:
            return self.bot.all_enemy_units.exclude_type(ENEMY_CIVILIANS)

    @property
    def creep(self) -> np.ndarray:
        return self.bot.state.creep.data_numpy.T == 1.0

    @property
    def vision(self) -> np.ndarray:
        return self.bot.state.visibility.data_numpy.T == 2

    # @property
    # def pathing(self) -> np.ndarray:
    #     return self.bot.game_info.pathing_grid.data_numpy.T == 1.0

    def is_visible(self, p: Point2 | Unit) -> bool:
        return self.bot.is_visible(p)

    @property
    def placement(self) -> np.ndarray:
        return self.bot.game_info.placement_grid.data_numpy.T == 1.0

    @property
    def time(self) -> float:
        return self.bot.time

    @property
    def gas_buildings(self) -> Units:
        return self.bot.gas_buildings

    @property
    def is_micro_map(self) -> bool:
        return self.bot.is_micro_map

    @property
    def structures(self) -> Units:
        return self.bot.structures

    @property
    def workers(self) -> Units:
        return self.bot.workers

    @property
    def townhalls(self) -> Units:
        return self.bot.townhalls

    @property
    def enemy_structures(self) -> Units:
        return self.bot.enemy_structures

    @cached_property
    def enemy_start_locations(self) -> list[Point]:
        return [p.rounded for p in self.bot.enemy_start_locations]

    @property
    def game_loop(self):
        return self.bot.state.game_loop

    @property
    def max_harvesters(self):
        return sum(
            (
                2 * self.all_taken_resources.mineral_field.amount,
                3 * self.all_taken_resources.vespene_geyser.amount,
            )
        )

    @cached_property
    def resources(self) -> Units:
        return self.bot.resources

    @cached_property
    def pathing(self) -> np.ndarray:
        return self.bot.mediator.get_map_data_object.get_pyastar_grid()

    @cached_property
    def pathable(self) -> np.ndarray:
        return self.bot.mediator.get_map_data_object.get_pyastar_grid() == 1.0

    @cached_property
    def air_pathing(self) -> np.ndarray:
        return self.bot.mediator.get_map_data_object.get_clean_air_grid()

    @cached_property
    def unit_commands(self) -> dict[int, ActionRawUnitCommand]:
        return {u: a for a in self.bot.state.actions_unit_commands for u in a.unit_tags}

    @cached_property
    def bases(self) -> list[Point]:
        if self.bot.is_micro_map:
            return []
        else:
            return [p.rounded for p in self.bot.expansion_locations_list]

    @property
    def race(self) -> Race:
        return self.bot.race

    @cached_property
    def geyers_taken(self) -> list[Unit]:
        # return [g for b in self.bases_taken for g in self.bot.expansion_locations_dict[b].vespene_geyser]
        return self.all_taken_resources.vespene_geyser

    @property
    def map_center(self) -> Point2:
        return self.bot.game_info.map_center

    @property
    def start_location(self) -> Point2:
        return self.bot.start_location

    @property
    def supply_used(self) -> float:
        return self.bot.supply_used

    @cached_property
    def bases_taken(self) -> set[Point]:
        return {
            p for b in self.bot.expansion_locations_list if (th := self.townhall_at.get(p := b.rounded)) and th.is_ready
        }

    @property
    def enemy_natural(self) -> Point2:
        return self.bot.mediator.get_enemy_nat

    @property
    def overlord_spots(self) -> list[Point2]:
        return self.bot.mediator.get_ol_spots

    def calculate_unit_value_weighted(self, unit_type: UnitTypeId) -> float:
        # TODO: learn value as parameters
        cost = self.bot.calculate_unit_value(unit_type)
        return cost.minerals + 2 * cost.vespene

    @cached_property
    def townhall_at(self) -> dict[Point, Unit]:
        return {b.position.rounded: b for b in self.bot.townhalls}

    @cached_property
    def resource_at(self) -> dict[Point, Unit]:
        return {r.position.rounded: r for r in self.bot.resources}

    @cached_property
    def all_taken_resources(self) -> Units:
        return Units(
            [
                r
                for base in self.bases
                if (th := self.townhall_at.get(base)) and th.is_ready
                for p in self.bot.expansion_resource_positions[base]
                if (r := self.resource_at.get(p))
            ],
            self.bot,
        )

    @cache
    def in_mineral_line(self, base: Point) -> Point:
        resource_positions = self.bot.expansion_resource_positions[base]
        return center(resource_positions).rounded

    @cache
    def behind_mineral_line(self, base: Point) -> Point2:
        return Point2(base).offset(HALF).towards(self.in_mineral_line(base), 10.0)

    def count(
        self, item: MacroId, include_pending: bool = True, include_planned: bool = True, include_actual: bool = True
    ) -> int:
        factor = 2 if item == UnitTypeId.ZERGLING else 1

        count = 0
        if include_actual:
            if item in WORKERS:
                count += self.bot.supply_workers
            else:
                count += len(self.actual_by_type[item])
        if include_pending:
            count += factor * len(self.pending_by_type[item])
        if include_planned:
            count += factor * sum(1 for _ in self.bot.planned_by_type(item))

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
            for h in self.bot.townhalls
        )

        return Cost(
            self.bot.state.score.collection_rate_minerals / 60.0,  # TODO: get from harvest assignment
            self.bot.state.score.collection_rate_vespene / 60.0,  # TODO: get from harvest assignment
            self.supply_income,  # TODO: iterate over pending
            larva_per_second,
        )

    @cached_property
    def actual_by_type(self) -> dict[MacroId, list[Unit]]:
        result = defaultdict(list)
        for unit in self.bot.all_own_units:
            if unit.is_ready:
                result[unit.type_id].append(unit)
        for upgrade in self.bot.state.upgrades:
            result[upgrade].append(upgrade)
        return result

    @cached_property
    def pending_by_type(self) -> defaultdict[MacroId, list[Unit]]:
        result = defaultdict(list)
        for unit in self.bot.all_own_units:
            if unit.is_ready:
                for order in unit.orders:
                    if item := ITEM_BY_ABILITY.get(order.ability.exact_id):
                        result[item].append(unit)
            else:
                result[unit.type_id].append(unit)
        return result

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
    def speedmining_positions(self) -> dict[Point, Point2]:
        return self.bot.speedmining_positions

    @property
    def supply_pending(self) -> int:
        return sum(
            provided * len(self.pending_by_type[unit_type])
            for unit_type, provided in SUPPLY_PROVIDED[self.bot.race].items()
        )

    def unit_data(self, unit_type_id: UnitTypeId) -> UnitTypeData:
        return self.bot.game_data.units[unit_type_id.value]

    @cache
    def build_time(self, unit_type: UnitTypeId) -> float:
        return self.bot.game_data.units[unit_type.value].cost.time

    @property
    def bank(self) -> Cost:
        return Cost(self.bot.minerals, self.bot.vespene, self.bot.supply_left, self.bot.larva.amount)

    @property
    def supply_income(self) -> float:
        return sum(
            len(self.pending_by_type[unit_type]) * provided / self.build_time(unit_type)
            for unit_type, provided in SUPPLY_PROVIDED[self.bot.race].items()
        )

    async def query_pathings(self, zipped_list: list[list[Unit | Point2 | Point3]]) -> list[float]:
        return await self.bot.client.query_pathings(zipped_list)

    async def query_pathing(self, start: Unit | Point2 | Point3, end: Point2 | Point3) -> float:
        return await self.bot.client.query_pathing(start, end)

    async def can_place_single(self, building: AbilityId | UnitTypeId, position: Point2) -> bool:
        return await self.bot.can_place_single(building, position)

    def find_path(self, start: Point2, target: Point2, air: bool = False) -> Point2:
        if air:
            grid = self.bot.mediator.get_air_grid
        else:
            grid = self.bot.mediator.get_ground_grid
        return self.bot.mediator.find_path_next_point(
            start=start,
            target=target,
            grid=grid,
            smoothing=True,
        )

    def find_safe_spot(self, start: Point2, air: bool = False, limit: int = 7) -> Point2:
        if air:
            grid = self.bot.mediator.get_air_grid
        else:
            grid = self.bot.mediator.get_ground_grid
        return self.bot.mediator.find_closest_safe_spot(
            from_pos=start,
            grid=grid,
            radius=limit,
        )

    def random_point(self, near: Point2 | None) -> Point2:
        a = self.bot.game_info.playable_area
        scale = min(self.bot.game_info.map_size) / 5
        if near:
            target = np.clip(
                np.random.normal((near.x, near.y), scale),
                (0.0, 0.0),
                (a.right, a.top),
            )
        else:
            target = np.random.uniform((a.x, a.y), (a.right, a.top))
        return Point2(target)

    @property
    def supply_planned(self) -> int:
        return sum(
            provided
            for unit_type, provided in SUPPLY_PROVIDED[self.bot.race].items()
            for _ in self.bot.planned_by_type(unit_type)
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
            and required_upgrade not in self.bot.state.upgrades
        ):
            yield required_upgrade

    def can_move(self, unit: Unit) -> bool:
        if unit.is_burrowed:
            if unit.type_id == UnitTypeId.INFESTORBURROWED:
                return True
            elif unit.type_id == UnitTypeId.ROACHBURROWED:
                return UpgradeId.TUNNELINGCLAWS in self.bot.state.upgrades
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
