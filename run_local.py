
import itertools
import sc2
import json
import cProfile
import pstats

from collections import defaultdict
from typing import Dict, Iterable, List, Tuple
from sc2.main import GameMatch, run_multiple_games

from sc2.data import Race, Difficulty, AIBuild, Result
from sc2.player import Bot, Computer

from src.pool12_allin import Pool12AllIn
from src.strategies.hatch_first import HatchFirst
from src.zerg import ZergAI
from src.dummy import DummyAI, DummyAI2

from test import CompetitiveBot

MAPS = [
    # 'BerlingradAIE',
    # 'CuriousMindsAIE',
    'HardwireAIE',
    # 'GlitteringAshesAIE',
    # 'OxideAIE',
    # 'RomanticideAIE',
    # '2000AtmospheresAIE',
    # 'LightshadeAIE',
    # 'JagannathaAIE',
    # 'BlackburnAIE',
]

RACES = [
    Race.Protoss,
    # Race.Terran,
    # Race.Zerg,
    # Race.Random,
]

BUILDS = [
    # AIBuild.Rush,
    AIBuild.Timing,
    # AIBuild.Power,
    # AIBuild.Macro,
    # AIBuild.Air,
]

DIFFICULTY = Difficulty.CheatInsane
REAL_TIME = False
RESULT_PATH = 'results.json'
SEED = 1

def create_bot():

    # ai = QueenBot()

    ai = ZergAI(strategy_cls=HatchFirst)
    ai.debug = True
    ai.game_step = 4

    # ai = Pool12AllIn()

    # ai = DummyAI()

    return Bot(Race.Zerg, ai)  

def create_opponents(difficulty) -> Iterable[Computer]:
    # return [Bot(Race.Zerg, DummyAI())]
    # yield Bot(Race.Zerg, Pool12AllIn())
    for race in RACES:
        for build in BUILDS:
            yield Computer(race, difficulty, ai_build=build)

if __name__ == "__main__":

    result_dict: Dict[Tuple[str, Race, AIBuild], List[Result]] = defaultdict(lambda:list())

    for i in itertools.count():
        games = [
            GameMatch(sc2.maps.get(map), [create_bot(), opponent], realtime=REAL_TIME, random_seed=SEED)
            for map in MAPS
            for opponent in create_opponents(DIFFICULTY)
        ]
        results = run_multiple_games(games)