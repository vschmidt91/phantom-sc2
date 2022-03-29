
from __future__ import annotations
from functools import cmp_to_key
from typing import TYPE_CHECKING, Iterable, List, Optional, Dict

import numpy as np

from dataclasses import dataclass
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from src.simulation.unit import SimulationUnit, SimulationUnitWithTarget, sample_path

from ..ai_component import AIComponent
if TYPE_CHECKING:
    from ..ai_base import AIBase
class Simulation(AIComponent):

    def __init__(self, ai: AIBase, units: Iterable[SimulationUnit], enemies: Iterable[SimulationUnit]) -> None:
        super().__init__(ai)
        self.units = list(units)
        self.enemies = list(enemies)

    def run(self, t: float, dt: float = 0.3) -> None:
        for t in np.arange(0, t, dt):
            self.step(t, dt)

    def step(self, t: float, dt: float) -> None:

        units_alive = [u for u in self.units if u.is_alive]
        enemies_alive = [u for u in self.enemies if u.is_alive]

        for unit in units_alive:
            if target := unit.select_target(enemies_alive):
                if weapon := unit.weapon_in_range_against(target):
                    target.damage += weapon.dps * dt
                else:
                    unit.position = unit.position.towards(target.position, unit.speed * dt, limit=True)

        for unit in enemies_alive:
            if target := unit.select_target(units_alive):
                if weapon := unit.weapon_in_range_against(target):
                    target.damage += weapon.dps * dt
                else:
                    unit.position = unit.position.towards(target.position, unit.speed * dt, limit=True)

    def weighted_result(self, position: Point2) -> float:
        def local_value(unit: SimulationUnit) -> float:
            v = self.ai.get_unit_cost(unit.type_id)
            v *= max(0, unit.damage / max(1, unit.health))
            d = unit.position.distance_to(position)
            v /= 5 + d
            # v /= 3 + t
            return v
        units_lost = sum(local_value(u) for u in self.units)
        enemies_killed = sum(local_value(u) for u in self.enemies)
        bias = 5
        return (bias + enemies_killed) / (bias + units_lost + enemies_killed)