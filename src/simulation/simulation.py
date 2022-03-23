
from __future__ import annotations
from functools import cmp_to_key
from typing import TYPE_CHECKING, Iterable, List, Optional

import numpy as np

from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from src.simulation.unit import SimulationUnit

from ..ai_component import AIComponent

if TYPE_CHECKING:
    from ..ai_base import AIBase
class Simulation(AIComponent):

    def __init__(self, ai: AIBase, units: Iterable[Unit], enemies: Iterable[Unit]) -> None:
        super().__init__(ai)
        self.army = { u.tag: SimulationUnit(u) for u in units }
        self.enemies = { u.tag: SimulationUnit(u) for u in enemies }

    def run(self, t: float, dt: float = 0.1) -> None:
        for t in np.arange(0, t, dt):
            self.step(dt)

    def step(self, dt: float) -> None:

        for unit in self.army.values():
            if target := unit.select_target(self.enemies.values()):
                if weapon := unit.weapon_against(target):
                    if unit.weapon_in_range_against(target):
                        target.health -= weapon.dps * dt
                    else:
                        contact = target.position.towards(unit.position, target.radius + weapon.range + unit.radius)
                        unit.position = unit.position.towards(contact, dt * unit.speed, True)

        for unit in self.enemies.values():
            if target := unit.select_target(self.army.values()):
                if weapon := unit.weapon_against(target):
                    if unit.weapon_in_range_against(target):
                        target.health -= weapon.dps * dt
                    else:
                        contact = target.position.towards(unit.position, target.radius + weapon.range + unit.radius)
                        unit.position = unit.position.towards(contact, dt * unit.speed, True)

        self.army = { t: u for t, u in self.army.items() if 0 < u.health }
        self.enemies = { t: u for t, u in self.enemies.items() if 0 < u.health }