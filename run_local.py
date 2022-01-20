
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
from src.lingflood import LingFlood
from src.strategies.hatch_first import HatchFirst
from src.strategies.pool12 import Pool12
from src.strategies.roach_rush import RoachRush
from src.zerg import ZergAI
from src.enums import PerformanceMode
from src.dummy import DummyAI, DummyAI2

from test import CompetitiveBot

MAPS = [
    # 'BerlingradAIE',
    # 'CuriousMindsAIE',
    # 'HardwireAIE',
    # 'GlitteringAshesAIE',
    # 'OxideAIE',
    # 'RomanticideAIE',
    '2000AtmospheresAIE',
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
    # AIBuild.Timing,
    # AIBuild.Power,
    AIBuild.Macro,
    # AIBuild.Air,
]

DIFFICULTY = Difficulty.CheatInsane

RESULT_PATH = 'results.json'

def create_bot():
    # ai = CompetitiveBot()
    # ai = Pool12AllIn()
    # ai = LingFlood()
    # ai = DummyAI()
    ai = ZergAI(strategy=HatchFirst())
    ai.debug = True
    ai.game_step = 8
    return Bot(Race.Zerg, ai)  

def create_opponents(difficulty) -> Iterable[Computer]:
    # return [Bot(Race.Zerg, DummyAI2())]
    for race in RACES:
        for build in BUILDS:
            yield Computer(race, difficulty, ai_build=build)

if __name__ == "__main__":

    result_dict: Dict[Tuple[str, Race, AIBuild], List[Result]] = defaultdict(lambda:list())

    for i in itertools.count():
        games = [
            GameMatch(sc2.maps.get(map), [create_bot(), opponent])
            for map in MAPS
            for opponent in create_opponents(DIFFICULTY)
        ]


        with cProfile.Profile() as pr:
            results = run_multiple_games(games)

        stats = pstats.Stats(pr)
        stats.sort_stats(pstats.SortKey.TIME)
        stats.dump_stats(filename='profiling.prof')

        for game, result in zip(games, results):
            opponent = game.players[1]
            key = f'{opponent.race.name} {opponent.ai_build.name} {game.map_sc2.name}'
            result_dict[key].append(result[game.players[0]].name)

        with open(RESULT_PATH, 'w') as file:
            json.dump(dict(result_dict), file, indent=4)