import gzip
import json
import lzma
import os
import pickle
import random
import sys
from pathlib import Path
from typing import Iterable
import datetime

import click
from loguru import logger
from sc2 import maps
from sc2.data import AIBuild, Difficulty, Race, Result
from sc2.main import run_game
from sc2.player import AbstractPlayer, Bot, Computer

# sys.path.append("ares-sc2/src/ares")
# sys.path.append("ares-sc2/src")
sys.path.append("ares-sc2")

from bot.main import PhantomBot
from bot.parameter.constants import PARAM_PRIORS
from bot.parameter.main import BotData, BotDataUpdate

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
@click.option("--data-file", default="data/params.pkl.gz", envvar="DATA_FILE")
@click.option("--data-json-file", default="data/params.json", envvar="DATA_JSON_FILE")
@click.option("--save-replay", default="resources/replays/local", envvar="SAVE_REPLAY")
@click.option("--realtime", default=False, envvar="REALTIME")
@click.option("--debug", default=True, envvar="DEBUG")
@click.option("--map-pattern", default="*AIE", envvar="MAP_PATTERN")
@click.option("--race", default=Race.Random.name, type=click.Choice([x.name for x in Race]), envvar="RACE")
@click.option("--difficulty", default=Difficulty.CheatInsane.name, type=click.Choice([x.name for x in Difficulty]), envvar="DIFFICULTY")
@click.option("--build", default=AIBuild.Rush.name, type=click.Choice([x.name for x in AIBuild]), envvar="BUILD")
def run_local(
    data_file: str,
    data_json_file: str,
    save_replay: str,
    realtime: bool,
    debug: bool,
    map_pattern: str,
    race: str,
    difficulty: str,
    build: str,
):

    data = BotData.from_priors(PARAM_PRIORS)
    if data_file:
        try:
            with gzip.GzipFile(data_file, "rb") as f:
                data = pickle.load(f)
        except Exception as e:
            logger.error(f"Error loading data file: {e}")
    parameters = data.sample_parameters()
    print(f"{parameters=}")

    ai = PhantomBot(parameters=parameters)
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

    opponent = Computer(Race[race], Difficulty[difficulty], AIBuild[build])

    print("Starting local game...")
    result = run_game(
        maps.get(random.choice(map_choices)),
        [bot, opponent],
        realtime=realtime,
        save_replay_as=replay_path,
    )
    print(f"Game finished: {result}")

    print("Updating parameters...")
    update = BotDataUpdate(
        parameters=parameters,
        result=result,
    )
    new_data = data + update
    if data_file:
        try:
            with gzip.GzipFile(data_file, "wb") as f:
                pickle.dump(new_data, f)
            with open(data_json_file, "w") as f:
                json.dump(new_data.to_dict(), f, indent=4)
        except Exception as e:
            logger.error(f"Error storing data file: {e}")


if __name__ == "__main__":
    run_local()
