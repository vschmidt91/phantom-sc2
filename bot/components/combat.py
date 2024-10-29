import math
import random
from abc import ABC
from dataclasses import dataclass
from enum import Enum, auto
from typing import TypeAlias

import numpy as np
from ares import AresBot
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.unit import Point2, Unit
from sc2.units import Units
from skimage.draw import disk

from ..action import Action, AttackMove, Move, UseAbility
from ..combat_predictor import CombatPrediction
from ..constants import CHANGELINGS, CIVILIANS, COOLDOWN, ENERGY_COST
from ..cost import Cost
from ..cython.cy_dijkstra import cy_dijkstra  # type: ignore
from .base import Component


class CombatStance(Enum):
    FLEE = auto()
    RETREAT = auto()
    FIGHT = auto()
    ADVANCE = auto()


Point: TypeAlias = tuple[int, int]
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


class Combat(Component, ABC):
    retreat_ground: DijkstraOutput
    retreat_air: DijkstraOutput
    confidence: float = 1.0
    _bile_last_used: dict[int, int] = dict()

    def do_combat(self, enemies: Units) -> None:

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

        def unit_value(cost: Cost):
            return max(0, cost.minerals + cost.vespene)

        army_cost = sum(
            unit_value(self.cost.of(unit.type_id))
            for unit in self.all_own_units.exclude_type(CIVILIANS).exclude_type(UnitTypeId.QUEEN)
        )
        enemy_cost = sum(
            unit_value(self.cost.of(unit.type_id)) for unit in self.all_enemy_units if unit.type_id not in CIVILIANS
        )
        self.confidence = np.log1p(army_cost) - np.log1p(enemy_cost)

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
        return None


def can_attack(unit: Unit, target: Unit) -> bool:
    if target.is_cloaked and not target.is_revealed:
        return False
    # elif target.is_burrowed and not any(self.units_detecting(target)):
    #     return False
    elif target.is_flying:
        return unit.can_attack_air
    else:
        return unit.can_attack_ground


@dataclass
class CombatAction(Action):
    unit: Unit
    prediction: CombatPrediction

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

        if not can_attack(self.unit, target) and not self.unit.is_detector:
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

        confidence = np.mean(
            [
                bot.confidence,
                self.prediction.confidence[self.unit.position.rounded],
            ]
        )

        if self.unit.type_id == UnitTypeId.QUEEN and not bot.has_creep(self.unit.position):
            stance = CombatStance.FLEE
        elif confidence < 0 and not bot.has_creep(self.unit.position):
            stance = CombatStance.FLEE
        elif self.unit.is_burrowed:
            stance = CombatStance.FLEE
        elif 1 < self.unit.ground_range:
            if 1 <= confidence:
                stance = CombatStance.ADVANCE
            elif 0 <= confidence:
                stance = CombatStance.FIGHT
            elif -1 <= confidence:
                stance = CombatStance.RETREAT
            elif len(retreat_path) < retreat_path_limit:
                stance = CombatStance.RETREAT
            else:
                stance = CombatStance.FLEE
        else:
            if -1 <= confidence:
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
