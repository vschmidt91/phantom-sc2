
from __future__ import annotations
from typing import TYPE_CHECKING

import numpy as np

from MapAnalyzer.MapData import MapData
from sc2.position import Point2
from sc2.unit import Unit

from .ai_component import AIComponent

if TYPE_CHECKING:
    from .ai_base import AIBase

class ValueMap(AIComponent):

    def __init__(self, ai: AIBase):
        super().__init__(ai)
        self.ground_vs_ground: np.ndarray = self.ai.map_analyzer.get_pyastar_grid(0)
        self.ground_vs_air: np.ndarray = self.ai.map_analyzer.get_clean_air_grid(0)
        self.air_vs_ground: np.ndarray = self.ai.map_analyzer.get_pyastar_grid(0)
        self.air_vs_air: np.ndarray = self.ai.map_analyzer.get_clean_air_grid(0)

    def add(self, unit: Unit, bonus_distance: float) -> None:
        weight = self.ai.get_unit_value(unit)
        if weight < 1:
            return
        range_vs_ground = unit.radius + self.ai.get_unit_range(unit, True, False) + bonus_distance
        range_vs_air = unit.radius + self.ai.get_unit_range(unit, False, True) + bonus_distance
        if unit.is_flying:
            if self.ai.techtree.units[unit.type_id].can_attack_ground:
                self.air_vs_ground = self.ai.map_analyzer.add_cost(unit.position, range_vs_ground, self.air_vs_ground, weight)
            if self.ai.techtree.units[unit.type_id].can_attack_air:
                self.air_vs_air = self.ai.map_analyzer.add_cost(unit.position, range_vs_air, self.air_vs_air, weight)
        else:
            if self.ai.techtree.units[unit.type_id].can_attack_ground:
                self.ground_vs_ground = self.ai.map_analyzer.add_cost(unit.position, range_vs_ground, self.ground_vs_ground, weight)
            if self.ai.techtree.units[unit.type_id].can_attack_air:
                self.ground_vs_air = self.ai.map_analyzer.add_cost(unit.position, range_vs_air, self.ground_vs_air, weight)

    def get_map_vs_ground(self) -> np.ndarray:
        return self.ground_vs_ground + self.air_vs_ground

    def get_map_vs_air(self) -> np.ndarray:
        return self.ground_vs_air + self.air_vs_air