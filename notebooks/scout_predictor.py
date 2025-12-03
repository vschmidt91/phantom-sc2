from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import product

import numpy as np
import pandas as pd
import sklearn
from sc2.data import Race
from sc2.dicts.unit_tech_alias import UNIT_TECH_ALIAS
from sc2.dicts.unit_unit_alias import UNIT_UNIT_ALIAS
from sc2.ids.unit_typeid import UnitTypeId
from sc2.units import Units

from phantom.common.unit_composition import UnitComposition
from phantom.common.utils import ALL_TRAINABLE


def _get_alias(unit_type: UnitTypeId) -> UnitTypeId | None:
    if unit_type == UnitTypeId.HIVE:
        return UnitTypeId.LAIR
    elif aliases := UNIT_TECH_ALIAS.get(unit_type):
        if len(aliases) == 1:
            return next(iter(aliases))
        raise NotImplementedError()
    elif alias := UNIT_UNIT_ALIAS.get(unit_type):
        return alias
    return None


TYPE_ALIASES = list((k, v) for k in reversed(UnitTypeId) if (v := _get_alias(k)) is not None)
TYPE_ALIASES_DICT = {k.value: v.value for k, v in TYPE_ALIASES}


@dataclass(frozen=True)
class PlayerVision:
    composition: UnitComposition
    enemy_composition: UnitComposition

    @classmethod
    def from_units(cls, units: Units) -> "PlayerVision":
        return PlayerVision(
            composition=Counter(u.type_id for u in units if u.is_mine),
            enemy_composition=Counter(u.type_id for u in units if u.is_enemy),
        )


class ScoutPredictor:
    def __init__(self, model: sklearn.base.BaseEstimator, unit_types: Sequence[UnitTypeId] = []) -> None:
        self.model = model
        self.unit_types = unit_types or list(ALL_TRAINABLE)
        self.unit_type_values = [u.value for u in self.unit_types]
        self.features = list(product([True, False], self.unit_type_values))

    def pivot(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.replace({"unit_type": TYPE_ALIASES_DICT})
        df = df.pivot_table(
            index=["replay_name", "game_loop", "player", "owner", "race", "enemy_race"],
            columns=["unit_type"],
            values="count",
            fill_value=0,
        )
        df = df.reindex(columns=self.unit_type_values, fill_value=0)
        return df

    def get_xy(self, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        x1 = self.get_x(df, 1)
        x2 = self.get_x(df, 2)
        x = np.concatenate((x1, x2), axis=0)
        y = np.concatenate((x2, x1), axis=0)
        return x, y

    def get_x(self, df: pd.DataFrame, player: int) -> np.ndarray:
        enemy = 3 - player
        df_own = df.loc[:, :, player, player, :, :]
        df_enemy = df.loc[:, :, player, enemy, :, :]
        df = df_own.merge(
            df_enemy, on=["replay_name", "game_loop", "race", "enemy_race"], how="left", suffixes=("_own", "_enemy")
        )
        df = df.fillna(0)
        df = df.reset_index(level=["game_loop", "race", "enemy_race"])
        x = df.to_numpy()
        return x

    def train(self, df: pd.DataFrame) -> None:
        df = self.pivot(df)
        x, y = self.get_xy(df)
        self.model.fit(x, y)

    def prediction_error(self, df: pd.DataFrame) -> float:
        df = self.pivot(df)
        x, y = self.get_xy(df)
        y_pred = self.model.predict(x)
        error = np.mean(np.abs(y - y_pred), axis=0)
        return error

    def predict(self, game_loop: int, vision: PlayerVision, player_races: Mapping[int, Race]) -> PlayerVision:
        player_id = 1
        enemy_id = 3 - player_id
        records = []
        for unit_type in self.unit_types:
            for owner, composition in (
                (player_id, vision.composition),
                (enemy_id, vision.enemy_composition),
            ):
                records.append(
                    dict(
                        replay_name="",
                        game_loop=game_loop,
                        player=player_id,
                        owner=owner,
                        race=player_races[player_id].value,
                        enemy_race=player_races[enemy_id].value,
                        unit_type=unit_type.value,
                        count=composition.get(unit_type, 0),
                    )
                )

        df = pd.DataFrame.from_records(records)
        df = self.pivot(df)
        x = self.get_x(df, 1)
        y = np.squeeze(self.model.predict(x))

        # prediction_game_loop = y[0]
        # prediction_race = y[1]
        # prediction_enemy_race = y[2]
        enemy = dict(zip(self.unit_types, y[3 : 3 + len(self.unit_types)], strict=True))
        enemy_own = dict(zip(self.unit_types, y[3 + len(self.unit_types) :], strict=True))
        enemy_vision = PlayerVision(enemy, enemy_own)
        return enemy_vision
