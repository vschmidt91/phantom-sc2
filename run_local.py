import itertools
from typing import Iterable

import sc2
from sc2.ids.buff_id import BuffId
from sc2.data import Race, Difficulty, AIBuild
from sc2.main import GameMatch, run_multiple_games
from sc2.player import AbstractPlayer, Bot, Computer
from src.strategies.pool_first import PoolFirst
from src.strategies.hatch_first import HatchFirst

from src.pool12_allin import Pool12AllIn
from src.ai_base import AIBase
from src.zerg import ZergAI
from src.strategies.terran_macro import TerranMacro
from tools.dummy import DummyAI

BuffId._missing_ = lambda _ : BuffId.NULL

MAPS = [
    "Equilibrium512V2AIE",
    "Goldenaura512V2AIE",
    "Gresvan512V2AIE",
    "HardLead512V2AIE",
    "Oceanborn512V2AIE",
    "SiteDelta512V2AIE",
]

RACES = [
    Race.Protoss,
    # Race.Terran,
    # Race.Zerg,
    # Race.Random,
]

BUILDS = [
    # AIBuild.Rush,
    # AIBuild.Timing,
    # AIBuild.Power,
    AIBuild.Macro,
    # AIBuild.Air,
]

DIFFICULTY = Difficulty.CheatInsane
REAL_TIME = False
RESULT_PATH = 'results.json'
SEED = 123


def create_bot():

    ai = ZergAI(strategy_cls=None)
    ai.debug = True
    ai.game_step = 1

    # ai = Pool12AllIn()

    # ai = DummyAI()

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
