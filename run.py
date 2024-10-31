import random
import sys
from pathlib import Path
from typing import Iterable

from sc2 import maps
from sc2.data import AIBuild, Difficulty, Race
from sc2.main import run_game
from sc2.player import AbstractPlayer, Bot, Computer

from ladder import run_ladder_game

sys.path.append("ares-sc2/src/ares")
sys.path.append("ares-sc2/src")
sys.path.append("ares-sc2")

from bot.phantom import PhantomBot  # type: ignore

MAPS_PATH: str = "C:\\Program Files (x86)\\StarCraft II\\Maps"
MAP_FILE_EXT: str = "SC2Map"
MAP_VETOS: list[str] = [
    "PlateauMicro_2",
    "BotMicroArena_6",
]

RACES = [
    # Race.Protoss,
    # Race.Terran,
    # Race.Zerg,
    Race.Random,
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


def create_bot(ai):
    return Bot(Race.Zerg, ai, 'PhantomBot')


def create_opponents(difficulty) -> Iterable[AbstractPlayer]:

    for race in RACES:
        for build in BUILDS:
            yield Computer(race, difficulty, ai_build=build)


if __name__ == "__main__":

    if "--LadderServer" in sys.argv:
        # Ladder game started by LadderManager
        print("Starting ladder game...")
        result, opponent_id = run_ladder_game(create_bot(PhantomBot()))
        print(result, " against opponent ", opponent_id)
    else:
        ai = PhantomBot(game_step_override=5)
        ai.debug = True
        map_list: list[str] = [
            p.name.replace(f".{MAP_FILE_EXT}", "")
            for p in Path(MAPS_PATH).glob(f"*.{MAP_FILE_EXT}")
            if p.is_file()
        ]
        for m in MAP_VETOS:
            map_list.remove(m)
        random_race = random.choice(RACES)
        enemy_build = random.choice(BUILDS)
        print("Starting local game...")
        run_game(
            maps.get(random.choice(map_list)),
            [
                create_bot(ai),
                Computer(random_race, Difficulty.CheatInsane, enemy_build),
            ],
            realtime=False,
        )
