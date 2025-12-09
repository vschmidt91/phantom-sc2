from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING

import numpy as np
from ares import UnitTreeQueryType
from cython_extensions import cy_dijkstra
from cython_extensions.dijkstra import DijkstraOutput
from loguru import logger
from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from phantom.common.action import Action, Attack, Move
from phantom.common.constants import (
    CIVILIANS,
    COMBATANT_STRUCTURES,
    ENEMY_CIVILIANS,
    HALF,
    MAX_UNIT_RADIUS,
    MIN_WEAPON_COOLDOWN,
)
from phantom.common.distribute import distribute
from phantom.common.parameter_sampler import ParameterSampler, Prior
from phantom.common.utils import (
    Point,
    air_dps_of,
    air_range_of,
    ground_dps_of,
    ground_range_of,
    structure_perimeter,
    to_point,
)
from phantom.micro.simulator import CombatResult, CombatSetup, CombatSimulator
from phantom.micro.utils import medoid, time_to_attack, time_to_kill

if TYPE_CHECKING:
    from phantom.main import PhantomBot


@dataclass(frozen=True)
class CombatPrediction:
    outcome_global: float
    outcome_local: Mapping[int, float]


class CombatParameters:
    def __init__(self, sampler: ParameterSampler) -> None:
        self.engagement_threshold = 0.0
        self.disengagement_threshold = 0.0
        self.global_engagement_level_param = sampler.add(Prior(0, 0.1))
        self.global_engagement_hysteresis_param = sampler.add(Prior(-1.5, 0.1, max=0))

    @property
    def global_engagement_hysteresis(self) -> float:
        return np.exp(self.global_engagement_hysteresis_param.value)

    @property
    def global_engagement_threshold(self) -> float:
        return np.tanh(self.global_engagement_level_param.value + self.global_engagement_hysteresis)

    @property
    def global_disengagement_threshold(self):
        return np.tanh(self.global_engagement_level_param.value - self.global_engagement_hysteresis)


@dataclass(frozen=True)
class CombatStepContext:
    state: "CombatState"
    combatants: Sequence[Unit]
    enemy_combatants: Sequence[Unit]
    prediction: CombatResult

    @cached_property
    def safe_combatants(self) -> Sequence[Unit]:
        safe_combatants = list[Unit]()
        for unit in self.combatants:
            grid = self.state.bot.mediator.get_air_grid if unit.is_flying else self.state.bot.ground_grid
            if self.state.bot.mediator.is_position_safe(
                grid=grid,
                position=unit.position,
            ):
                safe_combatants.append(unit)
        return safe_combatants

    @cached_property
    def retreat_to_creep_targets(self) -> Sequence[Point]:
        targets = list[Point]()
        for townhall in self.state.bot.townhalls.ready:
            targets.extend(structure_perimeter(townhall))
        for tumor in self.state.bot.structures(UnitTypeId.CREEPTUMORBURROWED):
            targets.append(to_point(tumor.position))
        return targets

    @cached_property
    def retreat_to_creep(self) -> DijkstraOutput | None:
        if self.retreat_to_creep_targets:
            return cy_dijkstra(
                self.state.bot.ground_grid.astype(np.float64), np.atleast_2d(self.retreat_to_creep_targets)
            )
        else:
            return None

    @cached_property
    def retreat_targets(self) -> Sequence[Point]:
        if self.safe_combatants:
            return list({to_point(u.position) for u in self.safe_combatants})
        elif self.state.bot.bases_taken:
            return [e.mineral_center for e in self.state.bot.bases_taken.values()]
        elif self.state.bot.workers:
            return list({to_point(u.position) for u in self.state.bot.workers})
        else:
            return []

    @cached_property
    def concentration_point(self) -> Point2:
        return medoid(self.retreat_targets)

    @cached_property
    def retreat_air(self) -> DijkstraOutput | None:
        if self.retreat_targets:
            return cy_dijkstra(
                self.state.bot.mediator.get_air_grid.astype(np.float64), np.atleast_2d(self.retreat_targets)
            )
        else:
            return None

    @cached_property
    def retreat_ground(self) -> DijkstraOutput | None:
        if self.retreat_targets:
            return cy_dijkstra(self.state.bot.ground_grid.astype(np.float64), np.atleast_2d(self.retreat_targets))
        else:
            return None

    @cached_property
    def concentrate_air(self) -> DijkstraOutput | None:
        if self.retreat_targets:
            return cy_dijkstra(
                self.state.bot.mediator.get_air_grid.astype(np.float64),
                np.array([to_point(self.concentration_point)]),
            )
        else:
            return None

    @cached_property
    def concentrate_ground(self) -> DijkstraOutput | None:
        if self.retreat_targets:
            return cy_dijkstra(
                self.state.bot.ground_grid.astype(np.float64),
                np.array([to_point(self.concentration_point)]),
            )
        else:
            return None

    @cached_property
    def attack_targets(self) -> Sequence[Point]:
        targets = list[Point2]()
        for s in self.state.bot.enemy_structures:
            targets.extend(structure_perimeter(s))
        for w in self.state.bot.enemy_workers:
            targets.append(to_point(w.position))
        if not targets:
            targets.extend(
                to_point(b) for b in self.state.bot.enemy_start_locations if not self.state.bot.is_visible(b)
            )
        return targets

    @cached_property
    def attack_air(self) -> DijkstraOutput | None:
        if self.attack_targets:
            return cy_dijkstra(
                self.state.bot.mediator.get_air_grid.astype(np.float64),
                np.atleast_2d(self.attack_targets),
            )
        else:
            return None

    @cached_property
    def attack_ground(self) -> DijkstraOutput | None:
        if self.attack_targets:
            return cy_dijkstra(
                self.state.bot.ground_grid.astype(np.float64),
                np.atleast_2d(self.attack_targets),
            )
        else:
            return None

    @classmethod
    def build(cls, state: "CombatState") -> "CombatStepContext":
        combatants = state.bot.units.exclude_type(CIVILIANS) | state.bot.structures(COMBATANT_STRUCTURES)
        enemy_combatants = state.bot.enemy_units.exclude_type(ENEMY_CIVILIANS) | state.bot.enemy_structures(
            COMBATANT_STRUCTURES
        )
        prediction = state.simulator.simulate(CombatSetup(units1=combatants, units2=enemy_combatants))
        return CombatStepContext(
            state=state,
            combatants=combatants,
            enemy_combatants=enemy_combatants,
            prediction=prediction,
        )


class CombatState:
    def __init__(self, bot: "PhantomBot", parameters: CombatParameters, simulator: CombatSimulator) -> None:
        self.bot = bot
        self.parameters = parameters
        self._attacking_global = True
        self._attacking_local = set[int]()
        self._targets: Mapping[int, Unit] = dict()
        self.simulator = simulator

    def _assign_targets(self, units: Sequence[Unit], targets: Sequence[Unit]) -> Mapping[int, Unit]:
        if not any(units) or not any(targets):
            return {}

        cost = time_to_attack(self.bot.mediator, units, targets) + time_to_kill(self.bot.mediator, units, targets)

        target_tag_to_index = {t.tag: i for i, t in enumerate(targets)}
        for i, unit in enumerate(units):
            if (previous_target := self._targets.get(unit.tag)) and (j := target_tag_to_index.get(previous_target.tag)):
                cost[i, j] = 0.0

        if np.isnan(cost).any():
            logger.error("assignment cost array contains NaN values")
            cost = np.nan_to_num(cost, nan=np.inf)

        assignment = distribute(
            [u.tag for u in units],
            targets,
            cost,
        )

        return assignment

    def on_step(self) -> "CombatStep":
        context = CombatStepContext.build(self)

        self._targets = self._assign_targets(context.combatants, context.enemy_combatants)
        targets = {self.bot.unit_tag_dict[tag]: target for tag, target in self._targets.items()}

        if context.prediction.outcome_global >= self.parameters.global_engagement_threshold:
            self._attacking_global = True
        elif context.prediction.outcome_global < self.parameters.global_disengagement_threshold:
            self._attacking_global = False

        for tag, outcome in context.prediction.outcome_local.items():
            if outcome >= self.parameters.engagement_threshold:
                self._attacking_local.add(tag)
            elif outcome < self.parameters.disengagement_threshold:
                self._attacking_local.discard(tag)

        return CombatStep(context, self._attacking_global, frozenset(self._attacking_local), targets)


class CombatStep:
    def __init__(
        self,
        context: CombatStepContext,
        attacking_global: bool,
        attacking_local: Set[int],
        targets: Mapping[Unit, Unit],
    ) -> None:
        self.bot = context.state.bot
        self.context = context
        self.attacking_global = attacking_global
        self.attacking_local = attacking_local
        self.targets = targets

    def retreat_with(self, unit: Unit, smoothing=3) -> Action:
        retreat_map = self.context.retreat_air if unit.is_flying else self.context.retreat_ground
        if not retreat_map:
            return self._move_to_safe_spot(unit)
        retreat_path = retreat_map.get_path(unit.position, limit=smoothing)
        if len(retreat_path) < smoothing:
            return self._move_to_safe_spot(unit)
        retreat_point = Point2(retreat_path[-1]).offset(HALF)
        return Move(retreat_point)

    def _move_to_safe_spot(self, unit: Unit) -> Action:
        retreat_grid = self.bot.mediator.get_air_grid if unit.is_flying else self.bot.ground_grid
        retreat_target = self.bot.mediator.find_closest_safe_spot(
            from_pos=unit.position,
            grid=retreat_grid,
        )
        move_target = self.bot.mediator.find_path_next_point(
            start=unit.position,
            target=retreat_target,
            grid=retreat_grid,
            smoothing=True,
        )
        return Move(move_target)

    def retreat_to_creep(self, unit: Unit, limit=3) -> Action | None:
        if not self.bot.has_creep(unit) and self.context.retreat_to_creep:
            path = self.context.retreat_to_creep.get_path(unit.position, limit=limit)
            if len(path) == 1:
                return None
            return Move(Point2(path[-1]).offset(HALF))
        return None

    def is_unit_safe(self, unit: Unit, weight_safety_limit: float = 1.0) -> bool:
        grid = self.bot.mediator.get_air_grid if unit.is_flying else self.bot.ground_grid
        return self.bot.mediator.is_position_safe(
            grid=grid, position=unit.position, weight_safety_limit=weight_safety_limit
        )

    def fight_with(self, unit: Unit) -> Action | None:
        ground_range = ground_range_of(unit)
        self.bot.has_creep(unit) or self.bot.enemy_race == Race.Zerg
        attack_ready = unit.weapon_cooldown <= MIN_WEAPON_COOLDOWN
        grid = self.bot.mediator.get_air_grid if unit.is_flying else self.bot.ground_grid
        self.bot.mediator.is_position_safe(
            grid=grid,
            position=unit.position,
        )

        if ground_range > 2 and attack_ready and (action := self._shoot_target_in_range(unit)):
            return action

        if (
            not unit.is_flying
            and not self.attacking_global
            and self.bot.enemy_race not in {Race.Zerg, Race.Random}
            and (action := self.retreat_to_creep(unit))
        ):
            return action

        if not (target := self.targets.get(unit)):
            return None

        if unit.tag in self.attacking_local:
            return Attack(target.position if ground_range < 2 else target)
        elif (
            (action := self.keep_unit_safe(unit))
            or (self.attacking_global and (action := self.attack_with(unit)))
            or (action := self.concentrate(unit))
        ):
            return action
        else:
            return None

    def attack_with(self, unit: Unit, smoothing: int = 3) -> Action | None:
        attack_map = self.context.attack_air if unit.is_flying else self.context.attack_ground
        if not attack_map:
            return None
        path = attack_map.get_path(unit.position, smoothing)
        # if len(path) < smoothing:
        #     return None
        target = Point2(path[-1]).offset(HALF)
        return Attack(target)

    def keep_unit_safe(self, unit: Unit) -> Action | None:
        if not self.is_unit_safe(unit):
            return self.retreat_with(unit)
        return None

    def concentrate(self, unit: Unit, limit: float = 10.0, smoothing: int = 3) -> Action | None:
        concentrate_map = self.context.concentrate_air if unit.is_flying else self.context.concentrate_ground
        if not concentrate_map:
            return None
        if concentrate_map.distance[to_point(unit.position)] < limit:
            return None
        path = concentrate_map.get_path(unit.position, limit=smoothing)
        if len(path) < smoothing:
            return None
        return Move(Point2(path[-1]).offset(HALF))

    def _target_priority(self, unit: Unit, target: Unit) -> float:
        dps = air_dps_of(target) if unit.is_flying else ground_dps_of(target)
        already_targeting = 10 * (unit.order_target == target.tag)
        health = 0.1 * (target.health + target.shield)
        return (1 + dps) * (1 + already_targeting) / (1 + health)

    def _shoot_target_in_range(self, unit: Unit) -> Action | None:
        candidates = list[Unit]()
        if unit.can_attack_ground:
            (query,) = self.bot.mediator.get_units_in_range(
                start_points=[unit],
                distances=[unit.radius + ground_range_of(unit) + MAX_UNIT_RADIUS],
                query_tree=UnitTreeQueryType.EnemyGround,
            )
            candidates.extend(filter(unit.target_in_range, query))
        if unit.can_attack_air:
            (query,) = self.bot.mediator.get_units_in_range(
                start_points=[unit],
                distances=[unit.radius + air_range_of(unit) + MAX_UNIT_RADIUS],
                query_tree=UnitTreeQueryType.EnemyFlying,
            )
            candidates.extend(filter(unit.target_in_range, query))

        if target := max(candidates, key=lambda u: self._target_priority(unit, u), default=None):
            return Attack(target)

        return None
