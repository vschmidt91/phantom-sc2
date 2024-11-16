from dataclasses import dataclass

import numpy as np
from sc2.data import Race

from bot.ai.utils import unit_composition_to_vector
from bot.common.unit_composition import UnitComposition


@dataclass(frozen=True)
class Observation:
    game_loop: int
    composition: UnitComposition
    enemy_composition: UnitComposition
    race: Race
    enemy_race: Race

    def to_array(self) -> np.ndarray:
        return np.concatenate(
            [
                [self.game_loop],
                unit_composition_to_vector(self.composition),
                unit_composition_to_vector(self.enemy_composition),
                [self.race.value, self.enemy_race.value],
            ]
        )
