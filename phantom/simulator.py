from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from sc2.unit import Unit
from sklearn.metrics import pairwise_distances

if TYPE_CHECKING:
    from phantom.main import PhantomBot


@dataclass
class CombatSetup:
    units1: Sequence[Unit]
    units2: Sequence[Unit]


@dataclass
class CombatResult:
    health_remaining: Mapping[int, float]
    outcome: Mapping[int, float]


class CombatSimulator(ABC):
    @abstractmethod
    def simulate(self, combat_setup: CombatSetup) -> CombatResult:
        raise NotImplementedError()


class StepwiseCombatSimulator(CombatSimulator):
    def __init__(self, bot: "PhantomBot") -> None:
        self.bot = bot
        self.time_horizon = 30.0
        self.num_steps = 100
        self.future_discount = 0.5
        self.vespene_weight = 2.0

    def is_attackable(self, u: Unit) -> bool:
        if u.is_burrowed or u.is_cloaked:
            return self.bot.mediator.get_is_detected(unit=u, by_enemy=u.is_mine)
        return True

    def simulate(self, setup: CombatSetup) -> CombatResult:
        units = [*setup.units1, *setup.units2]
        n1 = len(setup.units1)

        costs = [self.bot.cost.of(u.type_id) for u in units]
        values = np.array(
            [
                (c.minerals + self.vespene_weight * c.vespene) / max(1.0, u.shield_max + u.health_max)
                for u, c in zip(units, costs, strict=False)
            ]
        )

        ground_range = np.array([u.ground_range for u in units])
        air_range = np.array([u.air_range for u in units])
        ground_dps = np.array([u.ground_dps for u in units])
        air_dps = np.array([u.air_dps for u in units])
        radius = np.array([u.radius for u in units])
        attackable = np.array([self.is_attackable(u) for u in units])
        flying = np.array([u.is_flying for u in units])

        ground_selector = np.where(attackable & ~flying, 1.0, 0.0)
        air_selector = np.where(attackable & flying, 1.0, 0.0)
        dps = np.outer(ground_dps, ground_selector) + np.outer(air_dps, air_selector)
        ranges = np.outer(ground_range, ground_selector) + np.outer(air_range, air_selector)
        ranges += np.repeat(radius[:, np.newaxis], len(units), axis=1)
        ranges += np.repeat(radius[np.newaxis, :], len(units), axis=0)

        dps[:n1, :n1] = 0.0
        dps[n1:, n1:] = 0.0

        distance = pairwise_distances([u.position for u in units])
        movement_speed_vector = np.array([u.movement_speed for u in units])
        movement_speed = np.repeat(movement_speed_vector[:, np.newaxis], len(units), axis=1) + np.repeat(
            movement_speed_vector[np.newaxis, :], len(units), axis=0
        )

        health = np.array([u.health + u.shield for u in units])
        health_projection = health.copy()

        times = np.linspace(start=0.0, stop=self.time_horizon, num=self.num_steps + 1)[1:]
        times_diff = np.diff(times, prepend=0.0)

        loss_accumulation = np.zeros_like(health)

        for t, dt in zip(times, times_diff, strict=False):
            distance_projection = distance - movement_speed * t
            in_range = distance_projection <= ranges
            alive = health_projection > 0.0
            attack = (
                in_range
                & np.repeat(alive[:, np.newaxis], len(units), axis=1)
                & np.repeat(alive[np.newaxis, :], len(units), axis=0)
                & (dps > 0.0)
            )

            attack_weight = np.where(attack, 1.0, 0.0)
            attack_probability = attack_weight / np.maximum(1e-10, np.sum(attack_weight, axis=1, keepdims=True))

            damage_received = dt * (attack_probability * dps).sum(axis=0)
            loss_accumulation += damage_received * np.exp(-self.future_discount * t)
            health_projection -= damage_received

        mixing_own = np.reciprocal(1.0 + distance)
        mixing_enemy = mixing_own.copy()

        mixing_own[:n1, n1:] = 0.0
        mixing_own[n1:, :n1] = 0.0
        mixing_enemy[:n1, :n1] = 0.0
        mixing_enemy[n1:, n1:] = 0.0

        mixing_own /= mixing_own.sum(axis=1, keepdims=True)
        mixing_enemy /= mixing_enemy.sum(axis=1, keepdims=True)

        # losses = values * np.maximum(0.0, health - health_projection)
        losses_weighted = values * loss_accumulation
        losses_own = mixing_own @ losses_weighted
        losses_enemy = mixing_enemy @ losses_weighted
        outcome_vector = (losses_enemy - losses_own) / np.maximum(1e-10, losses_enemy + losses_own)

        health_remaining = {u.tag: max(0.0, h) for u, h in zip(units, health_projection, strict=False)}
        outcome = {u.tag: o for u, o in zip(units, outcome_vector, strict=True)}
        result = CombatResult(health_remaining=health_remaining, outcome=outcome)
        return result
