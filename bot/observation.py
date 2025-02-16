from collections import defaultdict
from dataclasses import dataclass
from functools import cache, cached_property
from itertools import chain, product
from typing import Iterable

import numpy as np
from sc2.dicts.unit_research_abilities import RESEARCH_INFO
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.game_state import ActionRawUnitCommand
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from sklearn.metrics import pairwise_distances

from bot.common.constants import (
    CIVILIANS,
    ENEMY_CIVILIANS,
    ITEM_BY_ABILITY,
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
from bot.common.cost import Cost
from bot.common.main import BotBase
from bot.common.utils import MacroId, center, logit_to_probability
from bot.data.constants import PARAM_COST_WEIGHTING


@dataclass(frozen=True)
class Observation:
    bot: BotBase

    @property
    def units(self) -> Units:
        if self.bot.is_micro_map:
            return self.bot.units
        else:
            return self.bot.units.exclude_type(CIVILIANS)

    @property
    def overseers(self) -> Units:
        return self.bot.units({UnitTypeId.OVERSEER, UnitTypeId.OVERSEERSIEGEMODE})

    @property
    def enemy_units(self) -> Units:
        if self.bot.is_micro_map:
            return self.bot.enemy_units
        else:
            return self.bot.all_enemy_units.exclude_type(ENEMY_CIVILIANS)

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
    def enemy_start_locations(self) -> list[Point2]:
        return self.bot.enemy_start_locations

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
    def creep(self) -> np.ndarray:
        return self.bot.state.creep.data_numpy.T == 1

    @cached_property
    def visibility(self) -> np.ndarray:
        return self.bot.state.visibility.data_numpy.T == 2

    @cached_property
    def pathing(self) -> np.ndarray:
        return self.bot.mediator.get_map_data_object.get_pyastar_grid()

    @cached_property
    def air_pathing(self) -> np.ndarray:
        return self.bot.mediator.get_map_data_object.get_clean_air_grid()

    @cached_property
    def unit_commands(self) -> dict[int, ActionRawUnitCommand]:
        return {u: a for a in self.bot.state.actions_unit_commands for u in a.unit_tags}

    @cached_property
    def bases(self) -> frozenset[Point2]:
        if self.bot.is_micro_map:
            return frozenset()
        else:
            return frozenset(self.bot.expansion_locations_list)

    @property
    def map_center(self) -> Point2:
        return self.bot.game_info.map_center

    @property
    def start_location(self) -> Point2:
        return self.bot.start_location

    @property
    def bases_taken(self) -> set[Point2]:
        return {b for b in self.bot.expansion_locations_list if (th := self.townhall_at.get(b)) and th.is_ready}

    @cached_property
    def distance_matrix(self) -> dict[tuple[Unit, Unit], float]:
        a = self.units
        b = self.enemy_units
        if not a:
            return {}
        if not b:
            return {}
        distances = pairwise_distances(
            [ai.position for ai in a],
            [bj.position for bj in b],
        )
        distance_matrix = {(ai, bj): distances[i, j] for (i, ai), (j, bj) in product(enumerate(a), enumerate(b))}
        return distance_matrix

    @property
    def cost_weighting(self) -> float:
        return logit_to_probability(self.bot.parameters[PARAM_COST_WEIGHTING])

    def calculate_unit_value_weighted(self, unit_type: UnitTypeId) -> float:
        cost = self.bot.calculate_unit_value(unit_type)
        return self.cost_weighting * cost.minerals + (1 - self.cost_weighting) * cost.vespene

    @property
    def townhall_at(self) -> dict[Point2, Unit]:
        return {b.position: b for b in self.bot.townhalls}

    @property
    def all_taken_resources(self) -> Units:
        return Units(
            chain.from_iterable(
                rs
                for p, rs in self.bot.expansion_locations_dict.items()
                if (th := self.townhall_at.get(p)) and th.is_ready
            ),
            self.bot,
        )

    @cache
    def in_mineral_line(self, base: Point2) -> Point2:
        if not (minerals := self.bot.expansion_locations_dict[base].mineral_field):
            return base
        return center(m.position for m in minerals)

    @cache
    def behind_mineral_line(self, base: Point2) -> Point2:
        return base.towards(self.in_mineral_line(base), 10.0)

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
    def supply_pending(self) -> int:
        return sum(
            provided * len(self.pending_by_type[unit_type])
            for unit_type, provided in SUPPLY_PROVIDED[self.bot.race].items()
        )

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
