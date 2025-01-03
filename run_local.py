import lzma
import os
import pickle
import random
import sys
from pathlib import Path
from typing import Iterable
import datetime

import click
from sc2 import maps
from sc2.data import AIBuild, Difficulty, Race
from sc2.main import run_game
from sc2.player import AbstractPlayer, Bot, Computer

from ladder import run_ladder_game

sys.path.append("ares-sc2/src/ares")
sys.path.append("ares-sc2/src")
sys.path.append("ares-sc2")

from bot.main import PhantomBot
from bot.ai.game import Game
# from bot.ai.replay import Replay

MAPS_PATH: str = "C:\\Program Files (x86)\\StarCraft II\\Maps"
MAP_FILE_EXT: str = "SC2Map"
MAP_VETOS: list[str] = [
    "PlateauMicro_2",
    "BotMicroArena_6",
    "Tier1MicroAIArena_v4",
    "Tier2MicroAIArena_v4",
]
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


@click.command()
@click.option("--save-replay", default="resources/replays/local", envvar="SAVE_REPLAY")
@click.option("--realtime", default=False, envvar="REALTIME")
@click.option("--debug", default=True, envvar="DEBUG")
@click.option("--map-pattern", default="*AIE", envvar="MAP_PATTERN")
@click.option("--race", default=Race.Random, type=click.Choice(Race), envvar="RACE")
@click.option("--difficulty", default=Difficulty.CheatInsane, type=click.Choice(Difficulty), envvar="DIFFICULTY")
@click.option("--build", default=AIBuild.Rush, type=click.Choice(AIBuild), envvar="BUILD")
def run_local(
    save_replay: str,
    realtime: bool,
    debug: bool,
    map_pattern: str,
    race: Race,
    difficulty: Difficulty,
    build: AIBuild,
):

    ai = PhantomBot()
    ai.config["Debug"] = debug

    name = type(ai).__name__
    bot = Bot(Race.Zerg, ai, name)

    replay_path: str | None = None
    timestamp = f"{datetime.datetime.now():%Y-%m-%d-%H-%M-%S}"
    if save_replay:
        replay_path = os.path.join(save_replay, f"{timestamp}.SC2REPLAY")
        os.makedirs(replay_path, exist_ok=True)

    map_choices = [
        p.name.replace(f".{MAP_FILE_EXT}", "")
        for p in Path(MAPS_PATH).glob(f"{map_pattern}.{MAP_FILE_EXT}")
        if p.is_file()
    ]

    print("Starting local game...")
    result = run_game(
        maps.get(random.choice(map_choices)),
        [
            bot,
            Computer(race, difficulty, build),
        ],
        realtime=realtime,
        save_replay_as=replay_path,
    )
    game_result = Game(
        result=result,
        observations=ai.observations,
        # replay=Replay(replay_path),
        race=race,
        enemy_race=race,
    )

    output_path = os.path.join(OUTPUT_DIR, f"{timestamp}.pkl.xz")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with lzma.open(output_path, "wb") as f:
        pickle.dump(game_result, f)


if __name__ == "__main__":
    run_local()
