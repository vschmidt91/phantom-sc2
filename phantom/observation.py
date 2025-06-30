from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
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
    COCOONS,
    ENEMY_CIVILIANS,
    MACRO_INFO,
    REQUIREMENTS_KEYS,
    SUPPLY_PROVIDED,
    WITH_TECH_EQUIVALENTS,
    ZERG_ARMOR_UPGRADES,
    ZERG_FLYER_ARMOR_UPGRADES,
    ZERG_FLYER_UPGRADES,
    ZERG_MELEE_UPGRADES,
    ZERG_RANGED_UPGRADES,
)
from phantom.common.cost import Cost
from phantom.common.utils import RNG, MacroId
from phantom.knowledge import Knowledge

type OrderTarget = Point2


class ObservationState:
    def __init__(self, bot: AresBot, knowledge: Knowledge):
        self.bot = bot
        self.knowledge = knowledge
        self.pathing = self._pathing()
        self.air_pathing = self._air_pathing()
        self.pending = dict[int, UnitTypeId]()
        self.pending_upgrades = set[UpgradeId]()

    def step(self, planned: Counter[MacroId]) -> "Observation":
        # for action in self.bot.state.actions_unit_commands:
        #     if item := ITEM_BY_ABILITY.get(action.exact_id):
        #         for trainer_tag in action.unit_tags:
        #             if trainer := self.bot._units_previous_map.get(trainer_tag):
        # if item in ALL_STRUCTURES:
        #     if trainer := trainer_by_tag.get(action.target_unit_tag):
        #         target = trainer.position
        #     else:
        #     target = action.target_world_space_pos
        #             # self.pending_structures[trainer] = item
        # elif isinstance(item, UpgradeId):
        #     self.pending_upgrades.add(item)

        # structure_at = {tuple(s.position.rounded): s for s in self.bot.structures}

        for tag, pending in list(self.pending.items()):
            if not (unit := self.bot.unit_tag_dict.get(tag)):
                # if pending in LARVA_COST:
                #     del self.pending[tag]
                #     continue
                # if pending in ALL_STRUCTURES:
                #     del self.pending[tag]
                #     continue
                # unit = self.bot._units_previous_map[tag]
                # position = unit.orders[0].target
                # structure = structure_at.get(position)
                # self.pending[structure.tag] = pending
                logger.debug(f"Trainer {tag=} is MIA for {pending=}")
                del self.pending[tag]
                continue
            if unit.is_structure:
                continue
            if unit.type_id in {UnitTypeId.EGG, UnitTypeId.RAVAGER, UnitTypeId.BROODLORD, UnitTypeId.LURKERMP}:
                continue
            if unit.type_id in COCOONS:
                continue
            if unit.is_idle and unit.type_id != UnitTypeId.LARVA:
                logger.warning(f"Trainer {unit=} became idle somehow")
                del self.pending[tag]
                continue
            ability = MACRO_INFO[unit.type_id][pending]["ability"]
            if unit.orders and unit.orders[0].ability.exact_id != ability:
                logger.warning(f"Trainer {unit=} has wrong order {unit.orders[0].ability.exact_id} for {pending=}")
                del self.pending[tag]
                continue

        # for error in self.bot.state.action_errors:
        #     # error_ability = AbilityId(error.ability_id)
        #     error_result = ActionResult(error.result)
        #     if (
        #         error_result in {ActionResult.CantBuildLocationInvalid, ActionResult.CouldntReachTarget}
        #         # and error_ability in {AbilityId.ZERGBUILD_HATCHERY}
        #         and (unit := self.bot._units_previous_map.get(error.unit_tag))
        #     ):
        #         self.pending_structures.pop(unit.tag, None)
        if self.bot.actual_iteration % 10 == 0:
            self.pathing = self._pathing()
            self.air_pathing = self._air_pathing()
        return Observation(self, planned)

    def _pathing(self) -> np.ndarray:
        return self.bot.mediator.get_map_data_object.get_pyastar_grid()

    def _air_pathing(self) -> np.ndarray:
        return self.bot.mediator.get_map_data_object.get_clean_air_grid()


class Observation:
    def __init__(self, state: ObservationState, planned: Counter[MacroId]):
        self.bot = state.bot
        self.context = state
        self.iteration = state.bot.actual_iteration
        self.knowledge = state.knowledge
        self.planned = planned
        self.unit_commands = {t: a for a in self.bot.state.actions_unit_commands for t in a.unit_tags}
        self.player_races = {k: Race(v) for k, v in self.bot.game_info.player_races.items()}
        self.workers_in_geysers = int(self.bot.supply_workers) - self.bot.workers.amount
        self.pathing = state.pathing
        self.air_pathing = state.air_pathing
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
        self.eggs = self.bot.eggs
        self.cocoons = self.units(COCOONS)
        self.townhalls = self.bot.townhalls
        self.enemy_structures = self.bot.enemy_structures
        self.game_loop = self.bot.state.game_loop
        self.resources = self.bot.resources

        self.actual_by_type = Counter[UnitTypeId](u.type_id for u in self.units if u.is_ready)
        self.actual_by_type[UnitTypeId.DRONE] = self.bot.supply_workers
        self.pending_by_type = Counter[UnitTypeId](state.pending.values())

        self.map_center = self.bot.game_info.map_center
        self.start_location = self.bot.start_location
        self.supply_used = self.bot.supply_used
        self.enemy_natural = self.bot.mediator.get_enemy_nat if not state.knowledge.is_micro_map else None
        self.overlord_spots = self.bot.mediator.get_ol_spots
        self.townhall_at = {tuple(b.position.rounded): b for b in self.bot.townhalls}
        self.resource_at = {tuple(r.position.rounded): r for r in self.bot.resources}

        self.bases_taken = set[tuple[int, int]]()
        if not state.knowledge.is_micro_map:
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

        self.supply_pending = 0
        self.supply_income = 0
        for unit_type, provided in SUPPLY_PROVIDED[self.bot.race].items():
            total_provided = provided * cy_unit_pending(self.bot, unit_type)
            self.supply_pending += total_provided
            self.supply_income += total_provided / self.knowledge.build_time[unit_type]

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

        self.income = Cost(
            self.bot.state.score.collection_rate_minerals / 60.0,  # TODO: get from harvest assignment
            self.bot.state.score.collection_rate_vespene / 60.0,  # TODO: get from harvest assignment
            self.supply_income,  # TODO: iterate over pending
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
        return all(self.count_actual(e) == 0 for e in WITH_TECH_EQUIVALENTS[unit])

    def count_actual(self, item: UnitTypeId) -> int:
        return self.actual_by_type[item]

    def count_pending(self, item: UnitTypeId) -> int:
        return self.pending_by_type[item]
        # if item in ALL_STRUCTURES:
        #     return self.pending_by_type[item]
        # else:
        #     return cy_unit_pending(self.bot, item)

    def count_planned(self, item: MacroId) -> int:
        factor = 2 if item == UnitTypeId.ZERGLING else 1
        return factor * self.planned[item]

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

        # if self.is_unit_missing(trainer):
        #     yield trainer
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
                # (UpgradeId.ZERGLINGMOVEMENTSPEED,),
                (UpgradeId.ZERGLINGMOVEMENTSPEED, UpgradeId.ZERGLINGATTACKSPEED),
                self.upgrade_sequence(ZERG_MELEE_UPGRADES),
                self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
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
            if upgrade in self.upgrades:
                continue
            if upgrade in self.context.pending_upgrades:
                continue
            return (upgrade,)
        return ()

    def _shootable_targets(self) -> Mapping[Unit, Sequence[Unit]]:
        units = self.combatants.filter(lambda u: u.ground_range > 1 and u.weapon_ready)

        points_ground = list[Point2]()
        points_air = list[Point2]()
        distances_ground = list[float]()
        distances_air = list[float]()
        for unit in units:
            base_range = 2 * unit.radius + unit.distance_to_weapon_ready
            if unit.can_attack_ground:
                points_ground.append(unit)
                distances_ground.append(base_range + unit.ground_range)
            if unit.can_attack_air:
                points_air.append(unit)
                distances_air.append(base_range + unit.air_range)

        ground_candidates = self.bot.mediator.get_units_in_range(
            start_points=points_ground,
            distances=distances_ground,
            query_tree=UnitTreeQueryType.EnemyGround,
            return_as_dict=True,
        )
        air_candidates = self.bot.mediator.get_units_in_range(
            start_points=points_air,
            distances=distances_air,
            query_tree=UnitTreeQueryType.EnemyFlying,
            return_as_dict=True,
        )
        targets = {u: ground_candidates.get(u.tag, []) + air_candidates.get(u.tag, []) for u in units}
        return targets
