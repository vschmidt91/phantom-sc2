import importlib
import inspect
import os
import random
import pathlib
import subprocess
import sys
from functools import reduce
from pathlib import Path
from typing import Iterable
import datetime

import click
from sc2 import maps
from sc2.data import AIBuild, Difficulty, Race
from sc2.main import run_game
from sc2.player import Bot, Computer

sys.path.append("ares-sc2/src/ares")
sys.path.append("ares-sc2/src")
sys.path.append("ares-sc2")
sys.path.append("src")
sys.path.append("bin")

from phantom.debug import PhantomBotDebug

MAPS_PATH: str = "C:\\Program Files (x86)\\StarCraft II\\Maps"
MAP_FILE_EXT: str = "SC2Map"


@click.command()
@click.option("--save-replay", default="resources/replays/local", envvar="SAVE_REPLAY")
@click.option("--training", default=True, envvar="TRAINING")
@click.option("--realtime", default=False, envvar="REALTIME")
@click.option("--map-pattern", default="*AIE", envvar="MAP_PATTERN")
@click.option("--race", default=Race.Random.name, type=click.Choice([x.name for x in Race]), envvar="RACE")
@click.option("--difficulty", default=Difficulty.CheatInsane.name, type=click.Choice([x.name for x in Difficulty]), envvar="DIFFICULTY")
@click.option("--build", default=AIBuild.Rush.name, type=click.Choice([x.name for x in AIBuild]), envvar="BUILD")
def run_local(
    save_replay: str,
    training: bool,
    realtime: bool,
    map_pattern: str,
    race: str,
    difficulty: str,
    build: str,
):

    # BASE_PATH = pathlib.Path(__file__).parent
    # CVXPY_CORE_PATH = (BASE_PATH / "cvxpy" / "cvxpy" / "cvxcore" / "python" / "cvxcore.py").as_posix()
    # with open(CVXPY_CORE_PATH) as fi:
    #     src_in = fi.read()
    # src_out = src_in.replace("from . import _cvxcore", "import _cvxcore")
    # with open(CVXPY_CORE_PATH, "w") as fo:
    #     fo.write(src_out)

    ai = PhantomBotDebug()
    ai.training = training
    bot = Bot(Race.Zerg, ai, "PhantomBot")

    replay_path: str | None = None
    if save_replay:
        replay_path = os.path.join(save_replay, f"{datetime.datetime.now():%Y-%m-%d-%H-%M-%S}.SC2REPLAY")
        os.makedirs(save_replay, exist_ok=True)

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
