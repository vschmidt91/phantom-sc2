from dataclasses import dataclass

from sc2.data import Race, Result

from bot.ai.observation import Observation

# from bot.ai.replay import Replay


@dataclass
class Game:
    result: Result
    observations: dict[int, Observation]
    # replay: Replay
    race: Race
    enemy_race: Race
