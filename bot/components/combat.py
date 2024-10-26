from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum, auto
from itertools import chain
from typing import TYPE_CHECKING, Iterable

import numpy as np
from ares import AresBot
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.unit import Point2, Unit
from skimage.draw import disk

from ..action import Action, AttackMove, Move, UseAbility
from ..constants import CHANGELINGS, CIVILIANS, COOLDOWN, ENERGY_COST
from ..cost import Cost
from ..cython.cy_dijkstra import cy_dijkstra  # type: ignore
from .component import Component

if TYPE_CHECKING:
    pass


class Enemy:
    def __init__(self, unit: Unit) -> None:
        self.unit = unit
        self.targets: list[CombatAction] = []
        self.threats: list[CombatAction] = []
        self.dps_incoming: float = 0.0
        self.estimated_survival: float = np.inf


class CombatStance(Enum):
    FLEE = auto()
    RETREAT = auto()
    FIGHT = auto()
    ADVANCE = auto()


class InfluenceMapEntry(Enum):
    DPS_GROUND_GROUND = 0
    DPS_GROUND_AIR = 1
    DPS_AIR_GROUND = 2
    DPS_AIR_AIR = 3
    HP_GROUND = 4
    HP_AIR = 5
    COUNT = 6


CONFIDENCE_MAP_SCALE = 6

Point = tuple[int, int]
HALF = Point2((0.5, 0.5))


@dataclass
class DijkstraOutput:
    prev_x: np.ndarray
    prev_y: np.ndarray
    dist: np.ndarray

    @classmethod
    def from_cy(cls, o) -> "DijkstraOutput":
        return DijkstraOutput(
            np.asarray(o.prev_x),
            np.asarray(o.prev_y),
            np.asarray(o.dist),
        )

    def get_path(self, target: Point, limit: float = math.inf):
        path: list[Point] = []
        x, y = target
        while len(path) < limit:
            path.append((x, y))
            x2 = self.prev_x[x, y]
            y2 = self.prev_y[x, y]
            if x2 < 0:
                break
            x, y = x2, y2
        return path


class CombatModule(Component):
    retreat_ground: DijkstraOutput
    retreat_air: DijkstraOutput
    estimated_survival: dict[int, float] = dict()
    confidence: float = 1.0
    _bile_last_used: dict[int, int] = dict()

    def do_combat(self) -> Iterable[Action]:

        army = self.units.filter(lambda u: u.type_id not in CIVILIANS).filter(lambda u: not(u.type_id == UnitTypeId.QUEEN and u.tag in self._inject_assignment and 20 <= u.energy))
        enemies = self.all_enemy_units

        self.ground_dps = np.zeros(self.game_info.map_size)
        self.air_dps = np.zeros(self.game_info.map_size)

        self.ground_dps[:, :] = 0.0
        self.air_dps[:, :] = 0.0
        for enemy in enemies:
            if enemy.can_attack_ground:
                r = enemy.radius + enemy.ground_range + 2.0
                d = disk(enemy.position, r, shape=self.ground_dps.shape)
                self.ground_dps[d] += enemy.ground_dps
            if enemy.can_attack_air:
                r = enemy.radius + enemy.air_range + 2.0
                d = disk(enemy.position, r, shape=self.air_dps.shape)
                self.air_dps[d] += enemy.air_dps

        retreat_cost_ground = self.mediator.get_map_data_object.get_pyastar_grid() + np.log1p(self.ground_dps)
        retreat_cost_air = self.mediator.get_map_data_object.get_clean_air_grid() + np.log1p(self.air_dps)
        retreat_targets = [w.position for w in self.workers] + [self.start_location]
        self.retreat_ground = DijkstraOutput.from_cy(
            cy_dijkstra(
                retreat_cost_ground.astype(np.float64),
                np.array(retreat_targets, dtype=np.intp),
            )
        )
        self.retreat_air = DijkstraOutput.from_cy(
            cy_dijkstra(
                retreat_cost_air.astype(np.float64),
                np.array(retreat_targets, dtype=np.intp),
            )
        )

        def time_until_in_range(unit: Unit, target: Unit) -> float:
            if target.is_flying:
                unit_range = unit.air_range
            else:
                unit_range = unit.ground_range
            unit_distance = np.linalg.norm(unit.position - target.position) - unit.radius - target.radius - unit_range
            return unit_distance / max(1.0, unit.movement_speed)

        self.estimated_survival.clear()

        dps_incoming: defaultdict[int, float] = defaultdict(lambda: 0)
        time_scale = 1 / 3
        for unit in army:
            for enemy in enemies:

                dps = unit.air_dps if enemy.is_flying else unit.ground_dps
                weight = math.exp(-max(0.0, time_scale * time_until_in_range(unit, enemy)))
                dps_incoming[enemy.tag] += dps * weight

                dps = enemy.air_dps if unit.is_flying else enemy.ground_dps
                weight = math.exp(-max(0.0, time_scale * time_until_in_range(enemy, unit)))
                dps_incoming[unit.tag] += dps * weight

        for unit in army | enemies:
            if 0 < dps_incoming[unit.tag]:
                self.estimated_survival[unit.tag] = (unit.health + unit.shield) / dps_incoming[unit.tag]
            else:
                self.estimated_survival[unit.tag] = np.inf

        def unit_value(cost: Cost):
            return cost.minerals + cost.vespene

        army_cost = sum(unit_value(self.cost.of(unit.type_id)) for unit in army)
        enemy_cost = sum(unit_value(self.cost.of(unit.type_id)) for unit in enemies)
        self.confidence = army_cost / max(1, army_cost + enemy_cost)

        changelings = list(chain.from_iterable(self.actual_by_type[t] for t in CHANGELINGS))
        for unit in changelings:
            if action := self.do_scout(unit):
                yield action
        for unit in army:
            if unit.type_id in {UnitTypeId.OVERSEER} and (action := self.do_spawn_changeling(unit)):
                yield action
            if unit.type_id in {UnitTypeId.ROACH} and (action := self.do_burrow(unit)):
                yield action
            elif unit.type_id in {UnitTypeId.ROACHBURROWED} and (action := self.do_unburrow(unit)):
                yield action
            elif unit.type_id in {UnitTypeId.RAVAGER} and (action := self.do_bile(unit)):
                yield action
            else:
                yield CombatAction(unit)

    def do_bile(self, unit: Unit) -> Action | None:

        ability = AbilityId.EFFECT_CORROSIVEBILE

        def bile_priority(target: Unit) -> float:
            if not target.is_enemy:
                return 0.0
            if not self.is_visible(target.position):
                return 0.0
            if not unit.in_ability_cast_range(ability, target.position):
                return 0.0
            if target.is_hallucination:
                return 0.0
            if target.type_id in CHANGELINGS:
                return 0.0
            priority = 10.0 + max(target.ground_dps, target.air_dps)
            priority /= 100.0 + target.health + target.shield
            priority /= 2.0 + target.movement_speed
            return priority

        if unit.type_id != UnitTypeId.RAVAGER:
            return None

        last_used = self._bile_last_used.get(unit.tag, 0)

        if self.state.game_loop < last_used + COOLDOWN[AbilityId.EFFECT_CORROSIVEBILE]:
            return None

        target = max(
            self.all_enemy_units,
            key=lambda t: bile_priority(t),
            default=None,
        )

        if not target:
            return None

        if bile_priority(target) <= 0:
            return None

        self._bile_last_used[unit.tag] = self.state.game_loop

        return UseAbility(unit, ability, target=target.position)

    def do_burrow(self, unit: Unit) -> Action | None:

        if (
            UpgradeId.BURROW in self.state.upgrades
            and unit.health_percentage < 1 / 3
            and unit.weapon_cooldown
            and not unit.is_revealed
        ):
            return UseAbility(unit, AbilityId.BURROWDOWN)

        return None

    def do_scout(self, unit: Unit) -> Action | None:
        if unit.is_idle:
            if self.time < 8 * 60:
                return AttackMove(unit, random.choice(self.enemy_start_locations))
            elif self.all_enemy_units.exists:
                target = self.all_enemy_units.random
                return AttackMove(unit, target.position)
            else:
                a = self.game_info.playable_area
                target = np.random.uniform((a.x, a.y), (a.right, a.top))
                target = Point2(target)
                if (unit.is_flying or self.in_pathing_grid(target)) and not self.is_visible(target):
                    return AttackMove(unit, target)
        return None

    def do_spawn_changeling(self, unit: Unit) -> Action | None:
        if unit.type_id in {UnitTypeId.OVERSEER, UnitTypeId.OVERSEERSIEGEMODE}:
            if self.in_pathing_grid(unit):
                ability = AbilityId.SPAWNCHANGELING_SPAWNCHANGELING
                if ENERGY_COST[ability] <= unit.energy:
                    return UseAbility(unit, ability)
        return None

    def do_unburrow(self, unit: Unit) -> Action | None:
        if unit.health_percentage == 1 or unit.is_revealed:
            return UseAbility(unit, AbilityId.BURROWUP)
        # elif unit.type_id == UnitTypeId.ROACHBURROWED and UpgradeId.TUNNELINGCLAWS in self.state.upgrades:
        #
        #     p = unit.position.rounded
        #     if 0.0 == self.ground_dps[p]:
        #         return DoNothing()
        #     else:
        #         retreat_map = self.retreat_ground
        #         if retreat_map.dist[p] == np.inf:
        #             retreat_point = self.start_location
        #         else:
        #             retreat_path = retreat_map.get_path(p, 3)
        #             retreat_point = Point2(retreat_path[-1]).offset(Point2((0.5, 0.5)))
        #         return Move(unit, retreat_point)
        return None


@dataclass
class CombatAction(Action):
    unit: Unit

    def target_priority(self, target: Unit) -> float:

        # from combat_manager:

        if target.is_hallucination:
            return 0.0
        if target.type_id in CHANGELINGS:
            return 0.0
        priority = 1e8

        # priority /= 1 + self.ai.distance_ground[target.position.rounded]
        priority /= 5 if target.is_structure else 1
        if target.is_enemy:
            priority /= 300 + target.shield + target.health
        else:
            priority /= 500

        # ---

        if not (self.unit.can_attack or self.unit.is_detector):
            return 0.0
        priority /= 8 + target.position.distance_to(self.unit.position)
        if self.unit.is_detector:
            if target.is_cloaked:
                priority *= 3.0
            if not target.is_revealed:
                priority *= 3.0

        return priority

    async def execute(self, bot: AresBot) -> bool:

        if self.unit.is_idle and self.unit.type_id not in {UnitTypeId.QUEEN}:
            if bot.time < 8 * 60:
                return await AttackMove(self.unit, random.choice(bot.enemy_start_locations)).execute(bot)
            elif bot.all_enemy_units.exists:
                target = bot.all_enemy_units.random
                return await AttackMove(self.unit, target.position).execute(bot)
            else:
                a = bot.game_info.playable_area
                target = np.random.uniform((a.x, a.y), (a.right, a.top))
                target = Point2(target)
                if (self.unit.is_flying or bot.in_pathing_grid(target)) and not bot.is_visible(target):
                    return await AttackMove(self.unit, target).execute(bot)
                return False

        target, priority = max(
            ((enemy, self.target_priority(enemy)) for enemy in bot.all_enemy_units),
            key=lambda t: t[1],
            default=(None, 0),
        )

        estimated_survival = bot.estimated_survival.get(self.unit.tag, np.inf)

        if not target:
            return True
        if priority <= 0:
            return True

        if self.unit.is_flying:
            retreat_map = bot.retreat_air
        else:
            retreat_map = bot.retreat_ground
        p = self.unit.position.rounded
        retreat_path_limit = 5
        retreat_path = retreat_map.get_path(p, retreat_path_limit)

        target_survival = bot.estimated_survival.get(target.tag, np.inf)

        if np.isinf(estimated_survival):
            if np.isinf(target_survival):
                confidence = 0.5
            else:
                confidence = 1.0
        elif np.isinf(target_survival):
            confidence = 0.0
        else:
            confidence = estimated_survival / (estimated_survival + target_survival)

        if self.unit.type_id == UnitTypeId.QUEEN and not bot.has_creep(self.unit.position):
            stance = CombatStance.FLEE
        elif bot.confidence < 0.5 and not bot.has_creep(self.unit.position):
            stance = CombatStance.FLEE
        elif self.unit.is_burrowed:
            stance = CombatStance.FLEE
        elif 1 < self.unit.ground_range:
            if 3 / 4 <= confidence:
                stance = CombatStance.ADVANCE
            elif 2 / 4 <= confidence:
                stance = CombatStance.FIGHT
            elif 1 / 4 <= confidence:
                stance = CombatStance.RETREAT
            elif len(retreat_path) < retreat_path_limit:
                stance = CombatStance.RETREAT
            else:
                stance = CombatStance.FLEE
        else:
            if 1 / 2 <= confidence:
                stance = CombatStance.FIGHT
            else:
                stance = CombatStance.FLEE

        if stance in {CombatStance.FLEE, CombatStance.RETREAT}:
            unit_range = bot.get_unit_range(self.unit, not target.is_flying, target.is_flying)

            if stance == CombatStance.RETREAT:
                if not self.unit.weapon_cooldown:
                    return await AttackMove(self.unit, target.position).execute(bot)
                elif (
                    self.unit.radius + unit_range + target.radius + self.unit.distance_to_weapon_ready
                    < self.unit.position.distance_to(target.position)
                ):
                    return await AttackMove(self.unit, target.position).execute(bot)

            if retreat_map.dist[p] == np.inf:
                retreat_point = bot.start_location
            else:
                retreat_point = Point2(retreat_path[-1]).offset(HALF)

            return await Move(self.unit, retreat_point).execute(bot)

        elif stance == CombatStance.FIGHT:
            return await AttackMove(self.unit, target.position).execute(bot)

        elif stance == CombatStance.ADVANCE:
            distance = self.unit.position.distance_to(target.position) - self.unit.radius - target.radius
            if self.unit.weapon_cooldown and 1 < distance:
                return await Move(self.unit, target.position).execute(bot)
            elif (
                self.unit.position.distance_to(target.position)
                <= self.unit.radius + bot.get_unit_range(self.unit) + target.radius
            ):
                return await AttackMove(self.unit, target.position).execute(bot)
            else:
                return await AttackMove(self.unit, target.position).execute(bot)

        return False
