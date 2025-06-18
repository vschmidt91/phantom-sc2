from collections import Counter, defaultdict
from collections.abc import Iterable
from itertools import chain

import numpy as np
from ares import AresBot, UnitTreeQueryType
from cython_extensions import cy_unit_pending
from loguru import logger
from sc2.data import Race
from sc2.dicts.unit_research_abilities import RESEARCH_INFO
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.game_data import UnitTypeData
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2, Point3
from sc2.unit import Unit
from sc2.units import Units

from phantom.common.constants import (
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
from phantom.common.cost import Cost
from phantom.common.utils import RNG, MacroId
from phantom.knowledge import Knowledge


class Observation:
    def __init__(self, bot: AresBot, knowledge: Knowledge, planned: Counter[MacroId]):
        self.bot = bot
        self.knowledge = knowledge
        self.planned = planned
        self.unit_commands = {t: a for a in self.bot.state.actions_unit_commands for t in a.unit_tags}
        self.player_races = {k: Race(v) for k, v in self.bot.game_info.player_races.items()}
        self.workers_in_geysers = int(self.bot.supply_workers) - self.bot.workers.amount
        self.pathing = self.bot.mediator.get_map_data_object.get_pyastar_grid()
        self.pathable = self.pathing == 1.0
        self.supply_planned = sum(
            provided * self.planned[unit_type] for unit_type, provided in SUPPLY_PROVIDED[self.bot.race].items()
        )
        self.unit_by_tag = self.bot.unit_tag_dict
        self.action_errors = self.bot.state.action_errors
        self.supply_workers = self.bot.supply_workers
        self.supply_cap = self.bot.supply_cap
        self.researched_speed = self.bot.already_pending_upgrade(UpgradeId.ZERGLINGMOVEMENTSPEED) > 0.0
        self.effects = self.bot.state.effects
        self.upgrades = self.bot.state.upgrades
        self.units = self.bot.all_own_units
        self.overseers = self.bot.units({UnitTypeId.OVERSEER, UnitTypeId.OVERSEERSIEGEMODE})
        self.enemy_units = self.bot.all_enemy_units
        self.combatants = self.bot.units if self.knowledge.is_micro_map else self.bot.units.exclude_type(CIVILIANS)
        self.enemy_combatants = (
            self.bot.enemy_units if self.knowledge.is_micro_map else self.bot.enemy_units.exclude_type(ENEMY_CIVILIANS)
        )
        self.creep = self.bot.state.creep.data_numpy.T == 1.0
        self.is_visible = self.bot.state.visibility.data_numpy.T == 2.0
        self.placement = self.bot.game_info.placement_grid.data_numpy.T == 1.0
        self.time = self.bot.time
        self.gas_buildings = self.bot.gas_buildings
        self.structures = self.bot.structures
        self.workers = self.bot.workers
        self.townhalls = self.bot.townhalls
        self.enemy_structures = self.bot.enemy_structures
        self.game_loop = self.bot.state.game_loop
        self.resources = self.bot.resources

        actual_by_type = defaultdict(list)
        for unit in self.bot.all_own_units:
            if unit.is_ready:
                actual_by_type[unit.type_id].append(unit)
        for upgrade in self.bot.state.upgrades:
            actual_by_type[upgrade].append(upgrade)
        self.actual_by_type = actual_by_type

        pending_by_type = defaultdict(list)
        for unit in self.bot.all_own_units:
            if unit.is_ready:
                for order in unit.orders:
                    if item := ITEM_BY_ABILITY.get(order.ability.exact_id):
                        pending_by_type[item].append(unit)
            else:
                pending_by_type[unit.type_id].append(unit)
        self.pending_by_type = pending_by_type

        self.air_pathing = self.bot.mediator.get_map_data_object.get_clean_air_grid()

        self.map_center = self.bot.game_info.map_center
        self.start_location = self.bot.start_location
        self.supply_used = self.bot.supply_used
        self.enemy_natural = self.bot.mediator.get_enemy_nat if not knowledge.is_micro_map else None
        self.overlord_spots = self.bot.mediator.get_ol_spots
        self.townhall_at = {tuple(b.position.rounded): b for b in self.bot.townhalls}
        self.resource_at = {tuple(r.position.rounded): r for r in self.bot.resources}

        self.bases_taken = set[tuple[int, int]]()
        if not knowledge.is_micro_map:
            self.bases_taken.update(
                p
                for b in self.bot.expansion_locations_list
                if (th := self.townhall_at.get(p := tuple(b.rounded))) and th.is_ready
            )

        self.all_taken_resources = Units(
            [
                r
                for base in self.knowledge.bases
                if (th := self.townhall_at.get(base)) and th.is_ready
                for p in self.knowledge.expansion_resource_positions[base]
                if (r := self.resource_at.get(p))
            ],
            self.bot,
        )
        self.max_harvesters = sum(
            (
                2 * self.all_taken_resources.mineral_field.amount,
                3 * self.all_taken_resources.vespene_geyser.amount,
            )
        )
        self.geyers_taken = self.all_taken_resources.vespene_geyser
        self.supply_pending = sum(
            provided * len(self.pending_by_type[unit_type])
            for unit_type, provided in SUPPLY_PROVIDED[self.bot.race].items()
        )
        self.bank = Cost(self.bot.minerals, self.bot.vespene, self.bot.supply_left, self.bot.larva.amount)

        larva_income = sum(
            sum(
                (
                    1 / 11 if h.is_ready else 0.0,
                    3 / 29 if h.has_buff(BuffId.QUEENSPAWNLARVATIMER) else 0.0,  # TODO: track actual injects
                )
            )
            for h in self.bot.townhalls
        )

        supply_income = sum(
            cy_unit_pending(self.bot, unit_type) * provided / self.knowledge.build_time[unit_type]
            for unit_type, provided in SUPPLY_PROVIDED[self.bot.race].items()
        )

        self.income = Cost(
            self.bot.state.score.collection_rate_minerals / 60.0,  # TODO: get from harvest assignment
            self.bot.state.score.collection_rate_vespene / 60.0,  # TODO: get from harvest assignment
            supply_income,  # TODO: iterate over pending
            larva_income,
        )
        self.shootable_targets = self._shootable_targets()

    def calculate_unit_value_weighted(self, unit_type: UnitTypeId) -> float:
        # TODO: learn value as parameters
        cost = self.bot.calculate_unit_value(unit_type)
        return cost.minerals + 2 * cost.vespene

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
            count += factor * self.planned[item]

        return count

    def unit_data(self, unit_type_id: UnitTypeId) -> UnitTypeData:
        return self.bot.game_data.units[unit_type_id.value]

    async def query_pathings(self, zipped_list: list[list[Unit | Point2 | Point3]]) -> list[float]:
        logger.debug(f"Query pathings {zipped_list=}")
        return await self.bot.client.query_pathings(zipped_list)

    async def query_pathing(self, start: Unit | Point2 | Point3, end: Point2 | Point3) -> float:
        logger.debug(f"Query pathing {start=} {end=}")
        return await self.bot.client.query_pathing(start, end)

    async def can_place_single(self, building: AbilityId | UnitTypeId, position: Point2) -> bool:
        logger.debug(f"Query placement {building=} {position=}")
        return await self.bot.can_place_single(building, position)

    def find_path(self, start: Point2, target: Point2, air: bool = False) -> Point2:
        grid = self.bot.mediator.get_air_grid if air else self.bot.mediator.get_ground_grid
        return self.bot.mediator.find_path_next_point(
            start=start,
            target=target,
            grid=grid,
            smoothing=True,
        )

    def find_safe_spot(self, start: Point2, air: bool = False, limit: int = 7) -> Point2:
        grid = self.bot.mediator.get_air_grid if air else self.bot.mediator.get_ground_grid
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
                RNG.normal((near.x, near.y), scale),
                (0.0, 0.0),
                (a.right, a.top),
            )
        else:
            target = RNG.uniform((a.x, a.y), (a.right, a.top))
        return Point2(target)

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
        return unit.movement_speed > 0

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
        elif unit in (UnitTypeId.MUTALISK, UnitTypeId.CORRUPTOR):
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

    def _shootable_targets(self) -> dict[Unit, list[Unit]]:
        units = self.combatants
        base_ranges = [u.radius for u in units]
        # base_ranges = [u.radius + MAX_UNIT_RADIUS + u.distance_to_weapon_ready for u in units]
        ground_ranges = [b + u.ground_range for u, b in zip(units, base_ranges, strict=False)]
        air_ranges = [b + u.air_range for u, b in zip(units, base_ranges, strict=False)]

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
            u: list(filter(u.target_in_range, a | b))
            for u, a, b in zip(units, ground_candidates, air_candidates, strict=False)
        }
        return targets
