from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, auto
from itertools import chain

import numpy as np
from ares import AresBot
from ares.consts import EngagementResult
from sc2.unit import Unit
from sc2.units import Units
from sklearn.metrics import pairwise_distances

from phantom.common.graph import graph_components


class CombatOutcome(Enum):
    Victory = auto()
    Defeat = auto()
    Draw = auto()


@dataclass(frozen=True)
class CombatPrediction:
    outcome: EngagementResult
    outcome_for: Mapping[int, EngagementResult]


def _required_distance(u: Unit, v: Unit) -> float:
    base_range = u.radius + (u.air_range if v.is_flying else u.ground_range) + v.radius
    distance = u.distance_to(v)
    return max(0.0, distance - base_range - u.distance_to_weapon_ready)


class CombatPredictor:
    def __init__(self, bot: AresBot, units: Units, enemy_units: Units):
        self.bot = bot
        self.units = units
        self.enemy_units = enemy_units
        self.horizon = 6
        self.enemy_horizon = 12
        self.prediction = self._prediction_sc2helper()

    def _prediction_sc2helper(self) -> CombatPrediction:
        n = len(self.units)
        len(self.enemy_units)

        units = list(chain(self.units, self.enemy_units))

        if not any(units):
            return CombatPrediction(EngagementResult.TIE, {})
        elif not any(self.units):
            return CombatPrediction(EngagementResult.LOSS_OVERWHELMING, {})
        elif not any(self.enemy_units):
            return CombatPrediction(EngagementResult.VICTORY_OVERWHELMING, {})

        distance_matrix = pairwise_distances(
            [u.position for u in self.units],
            [u.position for u in self.enemy_units],
        )
        can_shoot = np.where(distance_matrix < self.enemy_horizon, 1, 0)

        # contact_own = np.where(pairwise_distances([u.position for u in self.units]) < self.horizon, 1, 0)
        contact_enemy = np.where(pairwise_distances([u.position for u in self.enemy_units]) < self.horizon, 1, 0)

        adjacency_matrix = np.block([[np.zeros((n, n)), can_shoot], [can_shoot.T, contact_enemy]])

        # adjacency_matrix = np.zeros((n + m, n + m), dtype=float)
        # for (i, a), (dj, b) in product(enumerate(self.units), enumerate(self.enemy_units)):
        #     j = len(self.units) + dj
        #     if _required_distance(a, b) <= self.time_horizon:
        #         adjacency_matrix[i, j] = 1.0
        #     if _required_distance(b, a) <= self.time_horizon:
        #         adjacency_matrix[j, i] = 1.0

        # adjacency_matrix = np.maximum(adjacency_matrix, adjacency_matrix.T)
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
                outcome_for[u.tag] = local_outcome

        return CombatPrediction(outcome, outcome_for)
