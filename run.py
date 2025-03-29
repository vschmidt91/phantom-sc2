import asyncio
import random
import sys
from pathlib import Path
import datetime

from sc2.data import AIBuild, Difficulty, Race
from sc2.main import run_game
from sc2.maps import Map
from sc2.paths import Paths
from sc2.portconfig import Portconfig
from sc2.player import Bot, Computer

import os
import click
from loguru import logger
import yaml

sys.path.append("ares-sc2")  # required to import sc2_helper
sys.path.append("ares-sc2/src")  # required to import ares

from phantom.debug import PhantomBot, PhantomBotDebug
from phantom.ladder import join_ladder_game

MAP_EXT = "SC2Map"

def CommandWithConfigFile(config_file_param_name):

    class CustomCommandClass(click.Command):

        def invoke(self, ctx):
            config_file = ctx.params[config_file_param_name]
            if config_file is not None:
                with open(config_file) as f:
                    config_data = yaml.safe_load(f)
                ctx.params.update(config_data)
            return super(CustomCommandClass, self).invoke(ctx)

    return CustomCommandClass

@click.command(cls=CommandWithConfigFile("config"))
@click.option("--config", type=click.Path())
@click.option("--GamePort", "game_port", type=int)
@click.option("--StartPort", "start_port", type=int)
@click.option("--LadderServer", "ladder_server")
@click.option("--OpponentId", "opponent_id")
@click.option("--RealTime", "realtime", default=False)
@click.option("--name", default="PhantomBot")
@click.option("--save-replay", "save_replay")
@click.option("--training", default=False)
@click.option("--debug", default=False)
@click.option("--resign-after-iteration", type=int)
@click.option("--maps-path")
@click.option("--map-pattern", default="*")
@click.option("--race", default=Race.Zerg.name, type=click.Choice([x.name for x in Race]))
@click.option("--enemy-race", default=Race.Random.name, type=click.Choice([x.name for x in Race]))
@click.option(
    "--enemy-difficulty",
    default=Difficulty.CheatInsane.name,
    type=click.Choice([x.name for x in Difficulty]),
)
@click.option("--enemy-build", default=AIBuild.Rush.name, type=click.Choice([x.name for x in AIBuild]))
def run(
    config: str,
    game_port: int,
    start_port: int,
    ladder_server: str,
    opponent_id: str,
    realtime: bool,
    name: str,
    save_replay: str,
    training: bool,
    debug: bool,
    resign_after_iteration: int,
    maps_path: str,
    map_pattern: str,
    race: str,
    enemy_race: str,
    enemy_difficulty: str,
    enemy_build: str,
):

    logger.info("Setting up bot...")
    if debug:
        ai = PhantomBotDebug()
        ai.resign_after_iteration = resign_after_iteration
    else:
        ai = PhantomBot()
    ai.training = training
    ai.opponent_id = opponent_id
    bot = Bot(Race[race], ai, name)

    if ladder_server:
        logger.info("Starting ladder game...")
        port_config = Portconfig(
            server_ports=[start_port + 2, start_port + 3],
            player_ports=[[start_port + 4, start_port + 5]]
        )
        task = join_ladder_game(
            host=ladder_server,
            port=game_port,
            players=[bot],
            realtime=realtime,
            portconfig=port_config)
        result = asyncio.get_event_loop().run_until_complete(task)
    else:
        logger.info("Starting local game...")
        if save_replay:
            replay_path = os.path.join(save_replay, f"{datetime.datetime.now():%Y-%m-%d-%H-%M-%S}.SC2REPLAY")
            logger.info(f"Saving replay to {replay_path=}")
            os.makedirs(save_replay, exist_ok=True)
        else:
            replay_path = None

        maps_path_value = Path(maps_path) if maps_path else Paths.MAPS
        map_choices = list(maps_path_value.glob(f"{map_pattern}.{MAP_EXT}"))
        print(map_pattern)
        map_choice = random.choice(map_choices)
        logger.info(f"Map pick is {map_choice=}")
        opponent = Computer(Race[enemy_race], Difficulty[enemy_difficulty], AIBuild[enemy_build])
        result = run_game(
            Map(map_choice),
            [bot, opponent],
            realtime=realtime,
            save_replay_as=replay_path,
        )

    logger.info(f"Game finished with {result=}")


if __name__ == "__main__":
    run()
