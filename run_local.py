import os
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

sys.path.append("ares-sc2/src/ares")
sys.path.append("ares-sc2/src")
sys.path.append("ares-sc2")
sys.path.append("src")

from phantom.debug import PhantomBotDebug

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
@click.option("--map-pattern", default="*AIE", envvar="MAP_PATTERN")
@click.option("--race", default=Race.Random.name, type=click.Choice([x.name for x in Race]), envvar="RACE")
@click.option("--difficulty", default=Difficulty.CheatInsane.name, type=click.Choice([x.name for x in Difficulty]), envvar="DIFFICULTY")
@click.option("--build", default=AIBuild.Rush.name, type=click.Choice([x.name for x in AIBuild]), envvar="BUILD")
def run_local(
    save_replay: str,
    realtime: bool,
    map_pattern: str,
    race: str,
    difficulty: str,
    build: str,
):

    ai = PhantomBotDebug()
    bot = Bot(Race.Zerg, ai, "PhantomBot")

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


if __name__ == "__main__":
    run_local()
