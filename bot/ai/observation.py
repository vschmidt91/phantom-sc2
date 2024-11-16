from dataclasses import dataclass

import numpy as np

from bot.ai.utils import unit_composition_to_vector
from bot.common.unit_composition import UnitComposition


@dataclass(frozen=True)
class Observation:
    game_loop: int
    composition: UnitComposition
    enemy_composition: UnitComposition

    def to_array(self) -> np.ndarray:
        return np.concatenate(
            [
                [self.game_loop],
                unit_composition_to_vector(self.composition),
                unit_composition_to_vector(self.enemy_composition),
            ]
        )
