import os
import random
import sys
from pathlib import Path
import datetime

import click
from sc2 import maps
from sc2.data import AIBuild, Difficulty, Race
from sc2.main import run_game
from sc2.player import Bot, Computer

sys.path.append("ares-sc2")  # required to import sc2_helper
sys.path.append("ares-sc2/src")  # required to import ares

from phantom.debug import PhantomBotDebug


@click.command()
@click.option("--save-replay", default="resources/replays/local", envvar="SAVE_REPLAY")
@click.option("--training", default=True, envvar="TRAINING")
@click.option("--realtime", default=False, envvar="REALTIME")
@click.option("--maps-path", default="C:\\Program Files (x86)\\StarCraft II\\Maps", envvar="MAPS_PATH")
@click.option("--map-ext", default="SC2Map", envvar="MAP_EXT")
@click.option("--map-pattern", default="*", envvar="MAP_PATTERN")
@click.option("--race", default=Race.Random.name, type=click.Choice([x.name for x in Race]), envvar="RACE")
@click.option(
    "--difficulty",
    default=Difficulty.CheatInsane.name,
    type=click.Choice([x.name for x in Difficulty]),
    envvar="DIFFICULTY",
)
@click.option("--build", default=AIBuild.Rush.name, type=click.Choice([x.name for x in AIBuild]), envvar="BUILD")
def run_local(
    save_replay: str,
    training: bool,
    realtime: bool,
    maps_path: str,
    map_pattern: str,
    map_ext: str,
    race: str,
    difficulty: str,
    build: str,
):
    ai = PhantomBotDebug()
    ai.training = training
    bot = Bot(Race.Zerg, ai, "PhantomBot")

    replay_path: str | None = None
    if save_replay:
        replay_path = os.path.join(save_replay, f"{datetime.datetime.now():%Y-%m-%d-%H-%M-%S}.SC2REPLAY")
        os.makedirs(save_replay, exist_ok=True)

    map_choices = [
        p.name.replace(f".{map_ext}", "") for p in Path(maps_path).glob(f"{map_pattern}.{map_ext}") if p.is_file()
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
