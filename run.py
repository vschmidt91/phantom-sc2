import asyncio
import datetime
import os
import pathlib
import random
import sys

import click
import yaml
from loguru import logger
from sc2.data import AIBuild, Difficulty, Race
from sc2.main import run_game
from sc2.maps import Map
from sc2.paths import Paths
from sc2.player import Bot, Computer
from sc2.portconfig import Portconfig

from phantom.config import BotConfig
from phantom.ladder import join_ladder_game
from phantom.main import PhantomBot


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
@click.option("--config")
@click.option("--bot-config")
@click.option("--GamePort", "game_port", type=int)
@click.option("--StartPort", "start_port", type=int)
@click.option("--LadderServer", "ladder_server")
@click.option("--OpponentId", "opponent_id")
@click.option("--RealTime", "realtime", default=False)
@click.option("--save-replay")
@click.option("--maps-path", default=Paths.MAPS, type=click.Path())
@click.option("--map-pattern", default="*")
@click.option("--enemy-race", default=Race.Random.name, type=click.Choice([x.name for x in Race]))
@click.option(
    "--enemy-difficulty",
    default=Difficulty.CheatInsane.name,
    type=click.Choice([x.name for x in Difficulty]),
)
@click.option("--enemy-build", default=AIBuild.Rush.name, type=click.Choice([x.name for x in AIBuild]))
def run(
    config: str,
    bot_config: str,
    game_port: int,
    start_port: int,
    ladder_server: str,
    opponent_id: str,
    realtime: bool,
    save_replay: str,
    maps_path: pathlib.Path,
    map_pattern: str,
    enemy_race: str,
    enemy_difficulty: str,
    enemy_build: str,
):
    logger.info("Setting up bot...")
    logger.info(type(config))
    logger.info(maps_path)
    bot_config_value = BotConfig.from_yaml(bot_config)
    bot_config_value.opponent_id = opponent_id
    ai = PhantomBot(bot_config_value)
    race = ai.pick_race()
    bot = Bot(race, ai, ai.name)

    if ladder_server:
        logger.info("Starting ladder game...")
        port_config = Portconfig(
            server_ports=[start_port + 2, start_port + 3], player_ports=[[start_port + 4, start_port + 5]]
        )
        task = join_ladder_game(
            host=ladder_server, port=game_port, players=[bot], realtime=realtime, portconfig=port_config
        )
        result = asyncio.get_event_loop().run_until_complete(task)
    else:
        logger.info("Starting local game...")
        if save_replay:
            replay_path = os.path.join(save_replay, f"{datetime.datetime.now():%Y-%m-%d-%H-%M-%S}.SC2REPLAY")
            logger.info(f"Saving replay to {replay_path=}")
            os.makedirs(save_replay, exist_ok=True)
        else:
            replay_path = None

        map_choices = list(maps_path.glob(f"{map_pattern}.SC2MAP"))
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
