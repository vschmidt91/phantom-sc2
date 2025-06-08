from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import product

import numpy as np
import sklearn
from ares import ALL_STRUCTURES
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.units import Units

UNIT_TYPES = ALL_STRUCTURES | UNIT_TRAINED_FROM.keys()
UNIT_TYPE_VALUES = list(set(u.value for u in UNIT_TYPES))
FEATURES = [(o, t) for o, t in product([False, True], UNIT_TYPE_VALUES)]


type UnitComposition = Mapping[int, int]


@dataclass(frozen=True)
class PlayerVision:
    composition: UnitComposition
    enemy_composition: UnitComposition

    @classmethod
    def from_units(cls, units: Units) -> "PlayerVision":
        return PlayerVision(
            composition=Counter(u.type_id.value for u in units if u.is_mine),
            enemy_composition=Counter(u.type_id.value for u in units if u.is_enemy),
        )


class ScoutPredictor:
    def __init__(self, model: sklearn.base.BaseEstimator) -> None:
        self.model = model

    def predict(self, game_loop: int, vision: PlayerVision) -> PlayerVision:
        x = np.array(
            [
                [game_loop]
                + [vision.composition.get(u, 0) for u in UNIT_TYPE_VALUES]
                + [vision.enemy_composition.get(u, 0) for u in UNIT_TYPE_VALUES]
            ]
        )
        y = self.model.predict(x)[0, :]
        enemy_own_composition = dict[int, int]()
        enemy_composition = dict[int, int]()
        for yt, (own, t) in zip(y[1:], FEATURES, strict=False):
            if own:
                enemy_own_composition[t] = yt
            else:
                enemy_composition[t] = yt
        enemy_vision = PlayerVision(
            enemy_composition,
            enemy_own_composition,
        )
        return enemy_vision
