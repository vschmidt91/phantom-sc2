from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, auto
from itertools import product

import numpy as np
from ares import AresBot
from ares.consts import EngagementResult
from sc2.unit import Unit
from sc2.units import Units

from phantom.common.graph import graph_components


class CombatOutcome(Enum):
    Victory = auto()
    Defeat = auto()
    Draw = auto()


@dataclass(frozen=True)
class CombatPrediction:
    outcome: EngagementResult
    outcome_for: Mapping[Unit, EngagementResult]


def _required_distance(u: Unit, v: Unit) -> float:
    base_range = u.radius + (u.air_range if v.is_flying else u.ground_range) + v.radius
    distance = u.distance_to(v)
    return max(0.0, distance - base_range - u.distance_to_weapon_ready)


class CombatPredictor:
    def __init__(self, bot: AresBot, units: Units, enemy_units: Units):
        self.bot = bot
        self.units = units
        self.enemy_units = enemy_units
        self.time_horizon = 8
        self.prediction = self._prediction_sc2helper()

    def _prediction_sc2helper(self) -> CombatPrediction:
        units = list(self.units + self.enemy_units)

        if not any(units):
            return CombatPrediction(EngagementResult.TIE, {})

        adjacency_matrix = np.zeros((len(units), len(units)), dtype=float)
        for (i, a), (j, b) in product(enumerate(units), enumerate(units)):
            if a.alliance == b.alliance:
                pass
                # if a.distance_to(b) < self.time_horizon:
                #     adjacency_matrix[i, j] = adjacency_matrix[i, j] = 1.0
            else:
                if _required_distance(a, b) <= self.time_horizon:
                    adjacency_matrix[i, j] = 1.0
                if _required_distance(b, a) <= self.time_horizon:
                    adjacency_matrix[j, i] = 1.0

        adjacency_matrix = np.maximum(adjacency_matrix, adjacency_matrix.T)
        components = graph_components(adjacency_matrix)

        simulator_kwargs = dict(
            timing_adjust=True,
            good_positioning=True,
            workers_do_no_damage=False,
        )
        outcome = self.bot.mediator.can_win_fight(
            own_units=self.units, enemy_units=self.enemy_units, **simulator_kwargs
        )

        outcome_for = dict[Unit, EngagementResult]()
        for component in components:
            local_units = [units[i] for i in component]
            local_own = list(filter(lambda u: u.is_mine, local_units))
            local_enemies = list(filter(lambda u: u.is_enemy, local_units))
            if not any(local_own):
                local_outcome = EngagementResult.LOSS_OVERWHELMING if any(local_enemies) else EngagementResult.TIE
            elif not any(local_enemies):
                local_outcome = EngagementResult.VICTORY_OVERWHELMING
            else:
                local_outcome = self.bot.mediator.can_win_fight(
                    own_units=local_own,
                    enemy_units=local_enemies,
                    **simulator_kwargs,
                )

            for u in local_own:
                outcome_for[u] = local_outcome

        return CombatPrediction(outcome, outcome_for)
