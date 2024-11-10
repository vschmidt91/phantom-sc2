import math
from dataclasses import dataclass
from enum import Enum, auto
from functools import cached_property
from typing import TypeAlias

import numpy as np
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Point2, Unit

from bot.action import Action, AttackMove, Move
from bot.base import BotBase
from bot.constants import CHANGELINGS
from bot.cython.cy_dijkstra import cy_dijkstra  # type: ignore
from bot.predictor import Prediction


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


def can_attack(unit: Unit, target: Unit) -> bool:
    if target.is_cloaked and not target.is_revealed:
        return False
    # elif target.is_burrowed and not any(self.units_detecting(target)):
    #     return False
    elif target.is_flying:
        return unit.can_attack_air
    else:
        return unit.can_attack_ground


@dataclass(frozen=True)
class Combat:
    prediction: Prediction
    retreat_targets: list[Point2]

    def fight_with(self, context: BotBase, unit: Unit) -> Action | None:

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
            ((e, target_priority(e)) for e in self.prediction.context.enemy_units),
            key=lambda t: t[1],
            default=(None, 0),
        )

        if not target:
            return None
        if priority <= 0:
            return None

        if unit.is_flying:
            retreat_map = self.retreat_air
        else:
            retreat_map = self.retreat_ground

        x = round(unit.position.x)
        y = round(unit.position.y)
        retreat_path_limit = 5
        retreat_path = retreat_map.get_path((x, y), retreat_path_limit)

        confidence = self.prediction.confidence[unit.position.rounded]

        if unit.type_id == UnitTypeId.QUEEN and not context.has_creep(unit.position):
            stance = CombatStance.FLEE
        elif self.prediction.confidence_global < 0 and not context.has_creep(unit.position):
            stance = CombatStance.FLEE
        elif unit.is_burrowed:
            stance = CombatStance.FLEE
        elif 1 < unit.ground_range:
            if 1 <= confidence:
                stance = CombatStance.ADVANCE
            elif 0 <= confidence:
                stance = CombatStance.FIGHT
            elif -1 - math.exp(-unit.weapon_cooldown) <= confidence:
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
            unit_range = context.get_unit_range(unit, not target.is_flying, target.is_flying)

            if stance == CombatStance.RETREAT:
                if not unit.weapon_cooldown:
                    return AttackMove(unit, target.position)
                elif (
                    unit.radius + unit_range + target.radius + unit.distance_to_weapon_ready
                    < unit.position.distance_to(target.position)
                ):
                    return AttackMove(unit, target.position)

            if retreat_map.dist[x, y] == np.inf:
                retreat_point = context.start_location
            else:
                retreat_point = Point2(retreat_path[-1]).offset(HALF)

            return Move(unit, retreat_point)

        elif stance == CombatStance.FIGHT:
            return AttackMove(unit, target.position)

        elif stance == CombatStance.ADVANCE:
            distance = unit.position.distance_to(target.position) - unit.radius - target.radius
            if unit.weapon_cooldown and 1 < distance:
                return Move(unit, target.position)
            elif (
                unit.position.distance_to(target.position) <= unit.radius + context.get_unit_range(unit) + target.radius
            ):
                return AttackMove(unit, target.position)
            else:
                return AttackMove(unit, target.position)

        return None

    @cached_property
    def retreat_target_array(self) -> np.ndarray:
        return np.array(self.retreat_targets).astype(np.intp)

    @cached_property
    def threat_level(self) -> np.ndarray:
        return np.maximum(0, -self.prediction.confidence)

    @cached_property
    def retreat_air(self) -> DijkstraOutput:
        retreat_cost_air = (self.prediction.context.air_pathing + self.threat_level).astype(np.float64)
        cy_result = cy_dijkstra(retreat_cost_air, self.retreat_target_array)
        return DijkstraOutput.from_cy(cy_result)

    @cached_property
    def retreat_ground(self) -> DijkstraOutput:
        retreat_cost_air = (self.prediction.context.pathing + self.threat_level).astype(np.float64)
        cy_result = cy_dijkstra(retreat_cost_air, self.retreat_target_array)
        return DijkstraOutput.from_cy(cy_result)
