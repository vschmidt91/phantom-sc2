from dataclasses import dataclass
from functools import cached_property

import pandas as pd
from sc2.data import Result

from bot.ai.observation import Observation
from bot.ai.replay import Replay


@dataclass
class Game:
    result: Result
    observations: dict[int, Observation]
    replay: Replay

    @cached_property
    def to_dataframe(self) -> pd.DataFrame:
        df_observation = pd.DataFrame(self.observations)
        df_replay = self.replay.observations
        return pd.concat([df_observation, df_replay], axis=1)
