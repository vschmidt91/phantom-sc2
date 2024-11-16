import lzma
import os
import pickle
import random
import sys
from pathlib import Path
from typing import Iterable
import datetime

from sc2 import maps
from sc2.data import AIBuild, Difficulty, Race, Result
from sc2.main import run_game
from sc2.player import AbstractPlayer, Bot, Computer

from bot.ai.game import Game
from ai.replay import Replay
from ladder import run_ladder_game

sys.path.append("ares-sc2/src/ares")
sys.path.append("ares-sc2/src")
sys.path.append("ares-sc2")

from bot.main import PhantomBot

MAPS_PATH: str = "C:\\Program Files (x86)\\StarCraft II\\Maps"
MAP_FILE_EXT: str = "SC2Map"
MAP_VETOS: list[str] = [
    "PlateauMicro_2",
    "BotMicroArena_6",
]
REPLAY_DIR = os.path.join("resources", "replays", "local")
OUTPUT_DIR = os.path.join("resources", "games")

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

DIFFICULTY = Difficulty.VeryHard
REAL_TIME = False
RESULT_PATH = 'results.json'
SEED = 123




def create_opponents(difficulty) -> Iterable[AbstractPlayer]:

    for race in RACES:
        for build in BUILDS:
            yield Computer(race, difficulty, ai_build=build)


if __name__ == "__main__":

    ai = PhantomBot()
    bot = Bot(Race.Zerg, ai, 'PhantomBot')
    timestamp = f"{datetime.datetime.now():%Y-%m-%d-%H-%M-%S}"
    replay_path = os.path.join(REPLAY_DIR, f"{timestamp}.SC2REPLAY")
    os.makedirs(REPLAY_DIR, exist_ok=True)

    if "--LadderServer" in sys.argv:
        # Ladder game started by LadderManager
        print("Starting ladder game...")
        result, opponent_id = run_ladder_game(bot)
        print(result, " against opponent ", opponent_id)
    else:
        ai.config["Debug"] = True
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
        result = run_game(
            maps.get(random.choice(map_list)),
            [
                bot,
                Computer(random_race, Difficulty.CheatInsane, enemy_build),
            ],
            realtime=False,
            save_replay_as=replay_path,
        )
        game_result = Game(
            result=result,
            observations=ai.observations,
            replay=Replay(replay_path),
        )

        output_path = os.path.join(OUTPUT_DIR, f"{timestamp}.pkl.xz")
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with lzma.open(output_path, "wb") as f:
            pickle.dump(game_result, f)