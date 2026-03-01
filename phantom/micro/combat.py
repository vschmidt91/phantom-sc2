from collections.abc import Callable, Mapping, Sequence, Set
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING

import numpy as np
from ares import UnitTreeQueryType
from cython_extensions import cy_attack_ready, cy_dijkstra
from cython_extensions.dijkstra import DijkstraPathing
from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from phantom.common.action import Action, Attack, Move
from phantom.common.constants import (
    COMBATANT_STRUCTURES,
    HALF,
    MAX_UNIT_RADIUS,
)
from phantom.common.distribute import distribute
from phantom.common.point import to_point
from phantom.common.utils import (
    Point,
    air_dps_of,
    air_range_of,
    ground_dps_of,
    ground_range_of,
    structure_perimeter,
)
from phantom.learn.parameters import OptimizationTarget, ParameterManager, Prior
from phantom.micro.dead_airspace import DeadAirspace
from phantom.micro.simulator import CombatResult, CombatSetup, CombatSimulator
from phantom.micro.utils import medoid, time_to_attack, time_to_kill
from phantom.observation import Observation

if TYPE_CHECKING:
    from phantom.main import PhantomBot
    from phantom.micro.own_creep import OwnCreep


@dataclass(frozen=True)
class CombatPrediction:
    outcome_global: float
    outcome_local: Mapping[int, float]


class CombatParameters:
    def __init__(self, params: ParameterManager) -> None:
        self.engagement_threshold_transform = params.optimize[OptimizationTarget.CostEfficiency].add_scalar_transform(
            "engagement_threshold", Prior(0.0, 1.0), Prior(0.0, 1.0)
        )
        self._global_engagement_level = params.optimize[OptimizationTarget.CostEfficiency].add(
            "global_engagement_level", Prior(1.66, 0.1)
        )
        self._global_engagement_hysteresis = params.optimize[OptimizationTarget.CostEfficiency].add_softplus(
            "global_engagement_hysteresis", Prior(-1.519419353738057, 0.1)
        )

    @property
    def global_engagement_hysteresis(self) -> float:
        return self._global_engagement_hysteresis.value

    @property
    def global_engagement_threshold(self) -> float:
        return np.tanh(self._global_engagement_level.value + self.global_engagement_hysteresis)

    @property
    def global_disengagement_threshold(self):
        return np.tanh(self._global_engagement_level.value - self.global_engagement_hysteresis)


@dataclass(frozen=True)
class CombatStepContext:
    state: "CombatCommand"
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
        if self.state.bot.enemy_race in {Race.Zerg, Race.Random}:
            return self.state.own_creep.targets
        targets = list[Point]()
        for townhall in self.state.bot.townhalls.ready:
            targets.extend(structure_perimeter(townhall))
        for tumor in self.state.bot.structures(UnitTypeId.CREEPTUMORBURROWED):
            targets.append(to_point(tumor.position))
        return targets

    @cached_property
    def retreat_to_creep(self) -> DijkstraPathing | None:
        targets = self.retreat_to_creep_targets
        # creep_y, creep_x = self.state.bot.mediator.get_creep_edges
        # targets = list(zip(creep_x, creep_y, strict=False))
        if not targets:
            return None
        return cy_dijkstra(self.state.bot.ground_grid, np.atleast_2d(targets))

    @cached_property
    def safe_mineral_lines(self) -> Sequence[Point]:
        return [
            e.mineral_center
            for e in self.state.bot.bases_taken.values()
            if self.state.bot.mediator.is_position_safe(
                grid=self.state.bot.ground_grid,
                position=e.mineral_center,
            )
        ]

    @cached_property
    def safe_spine_positions(self) -> Sequence[Point]:
        return [
            e.spine_position
            for e in self.state.bot.bases_taken.values()
            if self.state.bot.mediator.is_position_safe(
                grid=self.state.bot.ground_grid,
                position=e.spine_position,
            )
        ]

    @cached_property
    def safe_workers(self) -> Sequence[Point]:
        return [
            to_point(w.position)
            for w in self.state.bot.workers
            if self.state.bot.mediator.is_position_safe(
                grid=self.state.bot.ground_grid,
                position=w.position,
            )
        ]

    @cached_property
    def retreat_targets(self) -> Sequence[Point]:
        return self.safe_mineral_lines or self.safe_workers
        # return self.safe_spine_positions or self.safe_mineral_lines or self.safe_workers

    @cached_property
    def concentration_point(self) -> Point2:
        return medoid(self.retreat_targets)

    @cached_property
    def retreat_air(self) -> DijkstraPathing | None:
        if self.retreat_targets:
            return cy_dijkstra(self.state.bot.mediator.get_air_grid, np.atleast_2d(self.retreat_targets))
        else:
            return None

    @cached_property
    def retreat_ground(self) -> DijkstraPathing | None:
        if self.retreat_targets:
            return cy_dijkstra(self.state.bot.ground_grid, np.atleast_2d(self.retreat_targets))
        else:
            return None

    @cached_property
    def concentrate_air(self) -> DijkstraPathing | None:
        if self.retreat_targets:
            return cy_dijkstra(
                self.state.bot.mediator.get_air_grid,
                np.array([to_point(self.concentration_point)]),
            )
        else:
            return None

    @cached_property
    def concentrate_ground(self) -> DijkstraPathing | None:
        if self.retreat_targets:
            return cy_dijkstra(
                self.state.bot.ground_grid,
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
    def attack_air(self) -> DijkstraPathing | None:
        if self.attack_targets:
            return cy_dijkstra(
                self.state.bot.mediator.get_air_grid,
                np.atleast_2d(self.attack_targets),
            )
        else:
            return None

    @cached_property
    def attack_ground(self) -> DijkstraPathing | None:
        if self.attack_targets:
            return cy_dijkstra(
                self.state.bot.ground_grid,
                np.atleast_2d(self.attack_targets),
            )
        else:
            return None

    @classmethod
    def build(
        cls,
        state: "CombatCommand",
        combatants: Sequence[Unit],
        enemy_combatants: Sequence[Unit],
        targets: Mapping[int, int],
    ) -> "CombatStepContext":
        attacking = set(state._attacking_local)
        attacking.update(u.tag for u in enemy_combatants)
        setup = CombatSetup(units1=combatants, units2=enemy_combatants, attacking=attacking, targets=targets)
        prediction = state.simulator.simulate(setup)
        return CombatStepContext(
            state=state,
            combatants=combatants,
            enemy_combatants=enemy_combatants,
            prediction=prediction,
        )


class CombatCommand:
    def __init__(
        self,
        bot: "PhantomBot",
        parameters: CombatParameters,
        simulator: CombatSimulator,
        own_creep: "OwnCreep",
        dead_airspace: DeadAirspace,
        considered_on_creep: Callable[[Unit], bool],
    ) -> None:
        self.bot = bot
        self.parameters = parameters
        self._attacking_global = True
        self._attacking_local = set[int]()
        self._targets: Mapping[int, Unit] = dict()
        self.simulator = simulator
        self.own_creep = own_creep
        self.dead_airspace = dead_airspace
        self._situation: CombatSituation | None = None
        self.considered_on_creep = considered_on_creep

    def _assign_targets(self, units: Sequence[Unit], targets: Sequence[Unit]) -> Mapping[int, Unit]:
        if not any(units) or not any(targets):
            return {}

        cost = time_to_attack(self.bot.mediator, units, targets) + time_to_kill(self.bot.mediator, units, targets)

        assignment = distribute(
            [u.tag for u in units],
            targets,
            cost,
            sticky=self._targets,
            sticky_cost=0.0,
        )

        return assignment

    @property
    def situation(self) -> "CombatSituation | None":
        return self._situation

    def on_step(self, observation: Observation) -> None:
        combatants = observation.combatants | self.bot.structures(COMBATANT_STRUCTURES)
        enemy_combatants = observation.enemy_combatants | self.bot.enemy_structures(COMBATANT_STRUCTURES)

        self._targets = self._assign_targets(combatants, enemy_combatants)

        target_tags = {t: u.tag for t, u in self._targets.items()}
        context = CombatStepContext.build(self, combatants, enemy_combatants, target_tags)

        if context.prediction.outcome_global >= self.parameters.global_engagement_threshold:
            self._attacking_global = True
        elif context.prediction.outcome_global < self.parameters.global_disengagement_threshold:
            self._attacking_global = False

        local_engagement_threshold = self.parameters.engagement_threshold_transform.transform(
            [
                1.0,
                context.prediction.outcome_global,
            ]
        )
        local_engagement_threshold = 0.0

        for tag, outcome in context.prediction.outcome_local.items():
            if outcome >= local_engagement_threshold:
                self._attacking_local.add(tag)
            elif outcome < local_engagement_threshold:
                self._attacking_local.discard(tag)

        targets = {self.bot.unit_tag_dict[tag]: target for tag, target in self._targets.items()}

        self._situation = CombatSituation(
            context,
            self._attacking_global,
            frozenset(self._attacking_local),
            targets,
            self.dead_airspace,
        )

    def get_actions(self, observation: Observation) -> Mapping[Unit, Action]:
        if self._situation is None:
            self.on_step(observation)
        situation = self._situation
        if situation is None:
            return {}
        return {
            combatant: action for combatant in observation.combatants if (action := situation.fight_with(combatant))
        }


class CombatSituation:
    def __init__(
        self,
        context: CombatStepContext,
        attacking_global: bool,
        attacking_local: Set[int],
        targets: Mapping[Unit, Unit],
        dead_airspace: DeadAirspace | None = None,
    ) -> None:
        self.bot = context.state.bot
        self.context = context
        self.attacking_global = attacking_global
        self.attacking_local = attacking_local
        self.targets = targets
        self.dead_airspace = dead_airspace

    @property
    def confidence_global(self) -> float:
        return self.context.prediction.outcome_global

    def retreat_with(self, unit: Unit, smoothing=3) -> Action | None:
        retreat_map = self.context.retreat_air if unit.is_flying else self.context.retreat_ground
        if not retreat_map:
            return self.move_to_safe_spot(unit)
        retreat_path = retreat_map.get_path(unit.position, limit=smoothing)
        if len(retreat_path) < smoothing:
            return None
        retreat_point = Point2(retreat_path[-1]).offset(HALF)
        return Move(retreat_point)

    def move_to_safe_spot(self, unit: Unit) -> Action:
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
        considered_on_creep = self.context.state.own_creep.is_on_own_creep(
            unit
        ) or self.context.state.considered_on_creep(unit)
        if not considered_on_creep and self.context.retreat_to_creep:
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

        if ground_range > 2 and (action := self._shoot_target_in_range(unit)):
            return action
        elif not (target := self.targets.get(unit)) or not self._can_target(unit, target):
            return None
        elif not self.attacking_global and not unit.is_flying and (action := self.retreat_to_creep(unit)):
            return action
        elif unit.tag in self.attacking_local:
            return Attack(target.position if ground_range < 2 else target)
        elif (
            (action := self.keep_unit_safe(unit, weight_safety_limit=10.0))
            or (self.attacking_global and (action := self.attack_with(unit)))
            or (action := self.retreat_with(unit))
        ):
            return action
        else:
            return None

    def attack_with(self, unit: Unit, smoothing: int = 3) -> Action | None:
        attack_map = self.context.attack_air if unit.is_flying else self.context.attack_ground
        grid = self.bot.mediator.get_air_grid if unit.is_flying else self.bot.ground_grid
        if not attack_map:
            return None
        path = attack_map.get_path(unit.position, smoothing)
        target = Point2(path[-1]).offset(HALF)
        if not self.bot.mediator.is_position_safe(grid=grid, position=target):
            return None
        return Attack(target)

    def keep_unit_safe(self, unit: Unit, weight_safety_limit: float = 1.0) -> Action | None:
        if not self.is_unit_safe(unit, weight_safety_limit=weight_safety_limit):
            return self.retreat_with(unit)
        return None

    def concentrate(self, unit: Unit, smoothing: int = 3) -> Action | None:
        concentrate_map = self.context.concentrate_air if unit.is_flying else self.context.concentrate_ground
        if not concentrate_map:
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

        def filter_target(target: Unit) -> bool:
            return (
                cy_attack_ready(self.bot, unit, target)
                and unit.target_in_range(target)
                and self._can_target(unit, target)
                and (
                    not (target.is_cloaked or target.is_burrowed)
                    or self.bot.mediator.get_is_detected(unit=target, by_enemy=target.is_mine)
                )
            )

        if unit.can_attack_ground:
            (query,) = self.bot.mediator.get_units_in_range(
                start_points=[unit],
                distances=[unit.radius + ground_range_of(unit) + MAX_UNIT_RADIUS],
                query_tree=UnitTreeQueryType.EnemyGround,
            )
            candidates.extend(filter(filter_target, query))
        if unit.can_attack_air:
            (query,) = self.bot.mediator.get_units_in_range(
                start_points=[unit],
                distances=[unit.radius + air_range_of(unit) + MAX_UNIT_RADIUS],
                query_tree=UnitTreeQueryType.EnemyFlying,
            )
            candidates.extend(filter(filter_target, query))

        if target := max(candidates, key=lambda u: self._target_priority(unit, u), default=None):
            return Attack(target)

        return None

    def _can_target(self, unit: Unit, target: Unit) -> bool:
        if not target.is_flying:
            return True
        if self.dead_airspace is None:
            return True
        return self.dead_airspace.check(unit, target)
