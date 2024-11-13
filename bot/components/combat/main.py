from dataclasses import dataclass
from enum import Enum, auto
from functools import cached_property
from typing import Callable

import numpy as np
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from scipy import ndimage

from bot.common.action import Action, AttackMove, HoldPosition, Move, UseAbility
from bot.common.constants import CHANGELINGS
from bot.common.main import BotBase
from bot.common.utils import Point, can_attack, disk
from bot.components.combat.presence import Presence
from bot.components.macro.strategy import Strategy
from bot.cython.dijkstra_pathing import DijkstraPathing

DpsProvider = Callable[[UnitTypeId], float]


class CombatStance(Enum):
    FLEE = auto()
    RETREAT = auto()
    HOLD = auto()
    FIGHT = auto()
    ADVANCE = auto()


HALF = Point2((0.5, 0.5))


@dataclass(frozen=True)
class Combat:
    bot: BotBase
    strategy: Strategy
    units: Units
    enemy_units: Units
    dps: DpsProvider
    pathing: np.ndarray
    air_pathing: np.ndarray
    retreat_targets: frozenset[Point2]
    attack_targets: frozenset[Point2]

    def retreat_with(self, unit: Unit, retreat_path_limit=5) -> Action:
        x = round(unit.position.x)
        y = round(unit.position.y)
        if unit.is_flying:
            retreat_map = self.retreat_air
        else:
            retreat_map = self.retreat_ground
        retreat_path = retreat_map.get_path((x, y), retreat_path_limit)
        if retreat_map.dist[x, y] == np.inf:
            retreat_point = self.bot.start_location
        else:
            retreat_point = Point2(retreat_path[-1]).offset(HALF)

        return Move(unit, retreat_point)

    def fight_with(self, unit: Unit) -> Action | None:

        def target_priority(t: Unit) -> float:

            # from combat_manager:

            if t.is_hallucination:
                return 0.0
            if t.type_id in CHANGELINGS:
                return 0.0
            p = 1e8

            # priority /= 1 + self.ai.distance_ground[target.position.rounded]
            p /= 5 if t.is_structure else 1
            if t.is_enemy:
                p /= 300 + t.shield + t.health
            else:
                p /= 500

            # ---

            if not can_attack(unit, t) and not unit.is_detector:
                return 0.0
            p /= 8 + t.position.distance_to(unit.position)
            if unit.is_detector:
                if t.is_cloaked:
                    p *= 3.0
                if not t.is_revealed:
                    p *= 3.0

            return p

        target, priority = max(
            ((e, target_priority(e)) for e in self.enemy_units),
            key=lambda t: t[1],
            default=(None, 0),
        )

        if not target:
            return None
        if priority <= 0:
            return None

        x = round(unit.position.x)
        y = round(unit.position.y)

        unit_range = unit.air_range if target.is_flying else unit.ground_range
        range_deficit = min(
            unit.sight_range, max(1, unit.distance_to(target) - unit.radius - target.radius - unit_range)
        )
        if self.attack_pathing.dist[x, y] == np.inf:
            attack_point = unit.position.towards(target, range_deficit, limit=True).rounded
        else:
            attack_path = self.attack_pathing.get_path((x, y), range_deficit)
            attack_point = attack_path[-1]
        #
        # confidence = max(
        #     self.confidence[x, y],
        #     self.confidence[attack_point],
        #     # self.strategy.confidence_global,
        # )

        if self.confidence[x, y] < 0 and not self.bot.has_creep(unit.position):
            return self.retreat_with(unit)
        elif unit.is_burrowed:
            return self.retreat_with(unit)
        if 0 == self.enemy_presence.dps[attack_point]:
            return AttackMove(unit, target.position)
        elif 0 < self.confidence[attack_point]:
            return AttackMove(unit, target.position)
        elif 0 == self.enemy_presence.dps[x, y]:
            return HoldPosition(unit)
        elif self.confidence[x, y] < -1:
            return self.retreat_with(unit)
        elif unit.radius + unit_range + target.radius + unit.distance_to_weapon_ready < unit.position.distance_to(
            target.position
        ):
            return UseAbility(unit, AbilityId.ATTACK, target)
        else:
            return self.retreat_with(unit)
        return None

    def do_unburrow(self, unit: Unit) -> Action | None:
        p = tuple[int, int](unit.position.rounded)
        confidence = self.confidence[p]
        if unit.health_percentage == 1 and 0 < confidence:
            return UseAbility(unit, AbilityId.BURROWUP)
        elif UpgradeId.TUNNELINGCLAWS not in self.bot.state.upgrades:
            return None
        elif 0 < self.enemy_presence.dps[p]:
            retreat_path = self.retreat_ground.get_path(p, 2)
            if self.retreat_ground.dist[p] == np.inf:
                retreat_point = self.bot.start_location
            else:
                retreat_point = Point2(retreat_path[-1]).offset(Point2((0.5, 0.5)))
            return Move(unit, retreat_point)
        return HoldPosition(unit)

    def do_burrow(self, unit: Unit) -> Action | None:
        if UpgradeId.BURROW not in self.bot.state.upgrades:
            return None
        elif 0.3 < unit.health_percentage:
            return None
        elif unit.is_revealed:
            return None
        elif not unit.weapon_cooldown:
            return None
        return UseAbility(unit, AbilityId.BURROWDOWN)

    @cached_property
    def dimensionality(self) -> np.ndarray:
        dimensionality_local = np.where(self.pathing == np.inf, 1.0, 2.0)
        dimensionality_filtered = ndimage.gaussian_filter(dimensionality_local, sigma=5.0)
        return dimensionality_filtered

    @cached_property
    def presence(self) -> Presence:
        return self.get_combat_presence(self.units)

    @cached_property
    def enemy_presence(self) -> Presence:
        return self.get_combat_presence(self.enemy_units)

    def get_combat_presence(self, units: Units) -> Presence:
        dps_map = np.zeros_like(self.pathing, dtype=float)
        health_map = np.zeros_like(self.pathing, dtype=float)
        for unit in units:
            dps = self.dps(unit.type_id)
            px, py = unit.position.rounded
            if 0 < dps:
                dx, dy = disk(unit.sight_range)
                d = px + dx, py + dy
                health_map[d] += unit.shield + unit.health
                dps_map[d] = np.maximum(dps_map[d], dps)
        return Presence(dps_map, health_map)

    @cached_property
    def force(self) -> np.ndarray:
        return self.presence.get_force(self.dimensionality)

    @cached_property
    def enemy_force(self) -> np.ndarray:
        return self.enemy_presence.get_force(self.dimensionality)

    @cached_property
    def confidence(self) -> np.ndarray:
        return np.log1p(self.force) - np.log1p(self.enemy_force)

    @cached_property
    def threat_level(self) -> np.ndarray:
        return self.enemy_presence.dps

    @cached_property
    def retreat_targets_rounded(self) -> list[Point]:
        return [(int(p[0]), int(p[1])) for p in self.retreat_targets]

    @cached_property
    def attack_targets_rounded(self) -> list[Point]:
        return [(int(p[0]), int(p[1])) for p in self.attack_targets]

    @cached_property
    def retreat_air(self) -> DijkstraPathing:
        return DijkstraPathing(self.air_pathing + self.threat_level, self.retreat_targets_rounded)

    @cached_property
    def retreat_ground(self) -> DijkstraPathing:
        return DijkstraPathing(self.pathing + self.threat_level, self.retreat_targets_rounded)

    @cached_property
    def attack_pathing(self) -> DijkstraPathing:
        return DijkstraPathing(self.pathing + self.threat_level, self.attack_targets_rounded)
