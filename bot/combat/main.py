import random
from dataclasses import dataclass
from enum import Enum, auto
from functools import cached_property
from typing import Callable

import numpy as np
from cython_extensions import cy_closest_to
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.combat.presence import Presence
from bot.common.action import Action, AttackMove, HoldPosition, Move, UseAbility
from bot.common.constants import CHANGELINGS
from bot.common.main import BotBase
from bot.common.utils import Point, can_attack, disk
from bot.cython.dijkstra_pathing import DijkstraPathing
from bot.macro.strategy import Strategy

DpsProvider = Callable[[UnitTypeId], float]


class CombatStance(Enum):
    FLEE = auto()
    RETREAT = auto()
    HOLD = auto()
    FIGHT = auto()
    ADVANCE = auto()


HALF = Point2((0.5, 0.5))


@dataclass(frozen=True)
class Attack(Action):
    unit: Unit
    target: Unit

    async def execute(self, bot: BotBase) -> bool:
        if self.target.is_memory:
            return self.unit.attack(self.target.position)
        else:
            return self.unit.attack(self.target)


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

    def retreat_with(self, unit: Unit, limit=5) -> Action | None:
        x = round(unit.position.x)
        y = round(unit.position.y)
        if unit.is_flying:
            retreat_map = self.retreat_air
        else:
            retreat_map = self.retreat_ground
        if retreat_map.dist[x, y] == np.inf:
            return Move(unit, random.choice(list(self.retreat_targets)))
        retreat_path = retreat_map.get_path((x, y), limit)
        if len(retreat_path) < limit:
            return None
        return Move(unit, Point2(retreat_path[-1]).offset(HALF))

    def advance_with(self, unit: Unit, limit=5) -> Action | None:
        x = round(unit.position.x)
        y = round(unit.position.y)
        if unit.is_flying:
            attack_map = self.attack_air
        else:
            attack_map = self.attack_ground
        if attack_map.dist[x, y] == np.inf:
            return Move(unit, random.choice(list(self.attack_targets)))
        attack_path = attack_map.get_path((x, y), limit)
        if len(attack_path) < limit:
            return None
        return Move(unit, Point2(attack_path[-1]).offset(HALF))

    def fight_with(self, unit: Unit) -> Action | None:

        def filter_target(t: Unit) -> bool:
            if t.is_hallucination:
                return False
            if t.type_id in CHANGELINGS:
                return False
            if not can_attack(unit, t) and not unit.is_detector:
                return False
            return True

        targets = [t for t in self.enemy_units if filter_target(t)]
        if not any(targets):
            return None

        target = cy_closest_to(unit.position, targets)

        x = round(unit.position.x)
        y = round(unit.position.y)

        unit_range = unit.air_range if target.is_flying else unit.ground_range
        is_in_range = unit.radius + unit_range + 0.5 + target.radius + unit.distance_to_weapon_ready > unit.distance_to(
            target
        )

        if self.confidence[x, y] < -1:
            return self.retreat_with(unit) or Move(unit, self.bot.start_location)
        elif unit.ground_range < 1:
            return AttackMove(unit, target.position)
        elif 1 < self.confidence[x, y]:
            return Attack(unit, target)
        elif unit.weapon_ready and is_in_range:
            return Attack(unit, target)
        elif 0 < self.enemy_presence.dps[x, y]:
            return self.retreat_with(unit) or Move(unit, self.bot.start_location)
        else:
            return self.advance_with(unit) or AttackMove(unit, target.position)

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
                r = 2 * unit.radius
                # r += 1
                # r += max(unit.ground_range, unit.air_range)
                r += unit.sight_range
                dx, dy = disk(r)
                d = px + dx, py + dy
                health_map[d] += unit.shield + unit.health
                dps_map[d] = np.maximum(dps_map[d], dps)
        return Presence(dps_map, health_map)

    @cached_property
    def force(self) -> np.ndarray:
        return self.presence.get_force()

    @cached_property
    def enemy_force(self) -> np.ndarray:
        return self.enemy_presence.get_force()

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
    def attack_air(self) -> DijkstraPathing:
        return DijkstraPathing(self.air_pathing + self.threat_level, self.attack_targets_rounded)

    @cached_property
    def attack_ground(self) -> DijkstraPathing:
        return DijkstraPathing(self.pathing + self.threat_level, self.attack_targets_rounded)
