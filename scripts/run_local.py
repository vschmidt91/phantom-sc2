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

from phantom.debug import PhantomBot, PhantomBotDebug


@click.command()
@click.option("--save-replay", default="")
@click.option("--debug", default=True)
@click.option("--training", default=True)
@click.option("--realtime", default=False)
@click.option("--maps-path", default="C:\\Program Files (x86)\\StarCraft II\\Maps")
@click.option("--map-ext", default="SC2Map")
@click.option("--map-pattern", default="*")
@click.option("--race", default=Race.Random.name, type=click.Choice([x.name for x in Race]))
@click.option(
    "--difficulty",
    default=Difficulty.CheatInsane.name,
    type=click.Choice([x.name for x in Difficulty]),
)
@click.option("--build", default=AIBuild.Rush.name, type=click.Choice([x.name for x in AIBuild]))
def run_local(
    save_replay: str,
    debug: bool,
    training: bool,
    realtime: bool,
    maps_path: str,
    map_pattern: str,
    map_ext: str,
    race: str,
    difficulty: str,
    build: str,
):
    ai = PhantomBotDebug() if debug else PhantomBot()
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
