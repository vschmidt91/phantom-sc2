import itertools
from typing import Iterable

import sc2
from sc2.data import Race, Difficulty, AIBuild
from sc2.main import GameMatch, run_multiple_games
from sc2.player import AbstractPlayer, Bot, Computer

from src.zerg import ZergAI

MAPS = [
    # 'BerlingradAIE',
    'CuriousMindsAIE',
    # 'HardwireAIE',
    # 'GlitteringAshesAIE',
    # '2000AtmospheresAIE',
    # 'BlackburnAIE',
]

RACES = [
    # Race.Protoss,
    # Race.Terran,
    Race.Zerg,
    # Race.Random,
]

BUILDS = [
    AIBuild.Rush,
    # AIBuild.Timing,
    # AIBuild.Power,
    # AIBuild.Macro,
    # AIBuild.Air,
]

DIFFICULTY = Difficulty.CheatInsane
REAL_TIME = False
RESULT_PATH = 'results.json'
SEED = 123


def create_bot():
    ai = ZergAI()
    ai.debug = True
    ai.game_step = 2

    # ai = Pool12AllIn()

    return Bot(Race.Zerg, ai, 'PhantomBot')


def create_opponents(difficulty) -> Iterable[AbstractPlayer]:
    # yield Bot(Race.Zerg, Pool12AllIn(), '12PoolBot')

    for race in RACES:
        for build in BUILDS:
            yield Computer(race, difficulty, ai_build=build)


if __name__ == "__main__":

    for i in itertools.count():
        games = [
            GameMatch(sc2.maps.get(map), [create_bot(), opponent], realtime=REAL_TIME, random_seed=SEED)
            for map in MAPS
            for opponent in create_opponents(DIFFICULTY)
        ]
        results = run_multiple_games(games)
