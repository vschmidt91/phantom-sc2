from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from cython_extensions import cy_dijkstra, cy_pick_enemy_target
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
    MIN_WEAPON_COOLDOWN,
)
from phantom.common.parameter_sampler import ParameterSampler, Prior
from phantom.common.utils import (
    Point,
    ground_range_of,
    structure_perimeter,
    to_point,
)
from phantom.micro.simulator import CombatResult, CombatSetup, StepwiseCombatSimulator
from phantom.micro.utils import assign_targets, get_shootable_targets, medoid

if TYPE_CHECKING:
    from phantom.main import PhantomBot


@dataclass(frozen=True)
class CombatPrediction:
    outcome_global: float
    outcome_local: Mapping[int, float]


class CombatParameters:
    def __init__(self, parameters: ParameterSampler) -> None:
        self.engagement_level_param = parameters.add(Prior(0, 1))
        self.engagement_hysteresis_param = parameters.add(Prior(-2, 1))
        self.global_engagement_level_param = parameters.add(Prior(0, 1))
        self.global_engagement_hysteresis_param = parameters.add(Prior(-2, 1))

    @property
    def engagement_hysteresis(self) -> float:
        return np.exp(self.engagement_hysteresis_param.value)

    @property
    def engagement_threshold(self) -> float:
        # return np.tanh(self.engagement_level_param.value + self.engagement_hysteresis)
        return 0.0

    @property
    def disengagement_threshold(self):
        # return np.tanh(self.engagement_level_param.value - self.engagement_hysteresis)
        return 0.0

    @property
    def global_engagement_hysteresis(self) -> float:
        return np.exp(self.global_engagement_hysteresis_param.value)

    @property
    def global_engagement_threshold(self) -> float:
        # return np.tanh(self.global_engagement_level_param.value + self.global_engagement_hysteresis)
        return 0.3

    @property
    def global_disengagement_threshold(self):
        # return np.tanh(self.global_engagement_level_param.value - self.global_engagement_hysteresis)
        return -0.3


@dataclass(frozen=True)
class CombatStepContext:
    state: "CombatState"
    combatants: Sequence[Unit]
    enemy_combatants: Sequence[Unit]
    prediction: CombatResult
    retreat_to_creep_pathing: DijkstraOutput
    retreat_air: DijkstraOutput
    retreat_ground: DijkstraOutput
    runby_pathing: DijkstraOutput
    shootable_targets: Mapping[Unit, Sequence[Unit]]
    targeting: Mapping[Unit, Unit]

    @classmethod
    def build(cls, state: "CombatState") -> "CombatStepContext":
        combatants = state.bot.units.exclude_type(CIVILIANS) | state.bot.structures(COMBATANT_STRUCTURES)
        enemy_combatants = state.bot.enemy_units.exclude_type(ENEMY_CIVILIANS) | state.bot.enemy_structures(
            COMBATANT_STRUCTURES
        )

        safe_combatants = list[Unit]()
        for unit in combatants:
            grid = state.bot.mediator.get_air_grid if unit.is_flying else state.bot.mediator.get_ground_grid
            if state.bot.mediator.is_position_safe(
                grid=grid,
                position=unit.position,
            ):
                safe_combatants.append(unit)

        retreat_to_creep_targets = list[Point]()
        for townhall in state.bot.townhalls.ready:
            retreat_to_creep_targets.extend(structure_perimeter(townhall))
        for tumor in state.bot.structures(UnitTypeId.CREEPTUMORBURROWED):
            retreat_to_creep_targets.append(to_point(tumor.position))
        if not retreat_to_creep_targets:
            retreat_to_creep_targets.append(to_point(state.bot.start_location))

        retreat_to_creep_pathing = cy_dijkstra(
            state.bot.mediator.get_ground_grid.astype(np.float64), np.atleast_2d(retreat_to_creep_targets)
        )

        retreat_targets = list()
        if safe_combatants:
            retreat_targets.append(medoid([u.position for u in safe_combatants]))

        if not retreat_targets:
            retreat_targets.extend(
                b
                for b in state.bot.bases_taken
                if state.bot.mediator.is_position_safe(
                    grid=state.bot.mediator.get_ground_grid,
                    position=Point2(b),
                )
            )

        if not retreat_targets:
            logger.warning("No retreat targets, falling back to start mineral line")
            p = state.bot.expansions[to_point(state.bot.start_location)].mineral_center
            retreat_targets.append(p)

        shootable_targets = get_shootable_targets(state.bot.mediator, combatants)

        retreat_targets_array = np.atleast_2d(retreat_targets).astype(int)
        retreat_air = cy_dijkstra(state.bot.mediator.get_air_grid.astype(np.float64), retreat_targets_array)
        retreat_ground = cy_dijkstra(state.bot.mediator.get_ground_grid.astype(np.float64), retreat_targets_array)

        runby_targets = list[Point2]()
        for s in state.bot.enemy_structures:
            runby_targets.extend(map(Point2, structure_perimeter(s)))
        for w in state.bot.enemy_workers:
            runby_targets.append(w.position)
        if not runby_targets:
            runby_targets.extend(state.bot.enemy_start_locations)
        runby_targets_array = np.atleast_2d(runby_targets).astype(int)
        runby_pathing = cy_dijkstra(
            state.bot.mediator.get_ground_grid.astype(np.float64),
            runby_targets_array,
        )

        prediction = state.simulator.simulate(CombatSetup(units1=combatants, units2=enemy_combatants))

        targeting = assign_targets(state.bot.mediator, combatants, enemy_combatants)

        return CombatStepContext(
            state=state,
            combatants=combatants,
            enemy_combatants=enemy_combatants,
            prediction=prediction,
            retreat_to_creep_pathing=retreat_to_creep_pathing,
            retreat_air=retreat_air,
            retreat_ground=retreat_ground,
            runby_pathing=runby_pathing,
            shootable_targets=shootable_targets,
            targeting=targeting,
        )


class CombatState:
    def __init__(self, bot: "PhantomBot", parameters: CombatParameters) -> None:
        self.bot = bot
        self.parameters = parameters
        self._attacking_global = True
        self._attacking_local = set[int]()
        self.simulator = StepwiseCombatSimulator(bot)

    def on_step(self) -> "CombatStep":
        context = CombatStepContext.build(self)

        if context.prediction.outcome_global >= self.parameters.global_engagement_threshold:
            self._attacking_global = True
        elif context.prediction.outcome_global < self.parameters.global_disengagement_threshold:
            self._attacking_global = False

        for tag, outcome in context.prediction.outcome_local.items():
            if outcome >= self.parameters.engagement_threshold:
                self._attacking_local.add(tag)
            elif outcome < self.parameters.disengagement_threshold:
                self._attacking_local.discard(tag)

        return CombatStep(context, self._attacking_global, frozenset(self._attacking_local))


class CombatStep:
    def __init__(self, context: CombatStepContext, attacking_global: bool, attacking_local: Set[int]) -> None:
        self.bot = context.state.bot
        self.context = context
        self.attacking_global = attacking_global
        self.attacking_local = attacking_local

    def retreat_with(self, unit: Unit, limit=3) -> Action:
        retreat_map = self.context.retreat_air if unit.is_flying else self.context.retreat_ground
        retreat_path = retreat_map.get_path(unit.position, limit=limit)
        if len(retreat_path) < limit:
            retreat_grid = self.bot.mediator.get_air_grid if unit.is_flying else self.bot.mediator.get_ground_grid
            retreat_point = self.bot.mediator.find_closest_safe_spot(
                from_pos=unit.position,
                grid=retreat_grid,
                radius=limit,
            )
        else:
            retreat_point = Point2(retreat_path[-1]).offset(HALF)
        return Move(retreat_point)

    def retreat_to_creep(self, unit: Unit, limit=3) -> Action:
        path = self.context.retreat_to_creep_pathing.get_path(unit.position, limit=limit)
        return Move(Point2(path[-1]).offset(HALF))

    def is_unit_safe(self, unit: Unit, weight_safety_limit: float = 1.0) -> bool:
        grid = self.bot.mediator.get_air_grid if unit.is_flying else self.bot.mediator.get_ground_grid
        return self.bot.mediator.is_position_safe(
            grid=grid, position=unit.position, weight_safety_limit=weight_safety_limit
        )

    def fight_with(self, unit: Unit) -> Action | None:
        ground_range = ground_range_of(unit)
        is_on_creep = self.bot.has_creep(unit) or self.bot.enemy_race == Race.Zerg
        attack_ready = unit.weapon_cooldown <= MIN_WEAPON_COOLDOWN
        grid = self.bot.mediator.get_air_grid if unit.is_flying else self.bot.mediator.get_ground_grid
        is_safe = self.bot.mediator.is_position_safe(
            grid=grid,
            position=unit.position,
        )

        if not unit.is_flying and not self.attacking_global and not is_on_creep and self.bot.enemy_race != Race.Zerg:
            return self.retreat_to_creep(unit)

        if attack_ready and (targets := self.context.shootable_targets.get(unit)):
            return Attack(cy_pick_enemy_target(enemies=targets))

        if not (target := self.context.targeting.get(unit)):
            return None

        if unit.tag in self.attacking_local:
            should_runby = not unit.is_flying and self.attacking_global and is_safe
            if should_runby:
                runby_target = Point2(self.context.runby_pathing.get_path(unit.position, 4)[-1]).offset(HALF)
                return Attack(runby_target)
            elif ground_range < 2:
                return Attack(target.position)
            else:
                return Attack(target)
        else:
            return self.retreat_with(unit)
