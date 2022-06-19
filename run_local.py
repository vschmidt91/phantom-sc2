
from collections import defaultdict
from typing import Dict, Iterable, List, Tuple
import itertools
import sc2

from sc2.main import GameMatch, run_multiple_games

from sc2.data import Race, Difficulty, AIBuild, Result
from sc2.player import AbstractPlayer, Bot, Computer

from src.strategies.hatch_first import HatchFirst
from src.strategies.pool_first import PoolFirst
from src.zerg import ZergAI

from Rasputin.src.zerg import ZergAI as Rasputin
from src.pool12_allin import Pool12AllIn


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

    ai = ZergAI(PoolFirst)
    ai.debug = True
    ai.game_step = 1

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