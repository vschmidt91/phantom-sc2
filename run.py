import datetime
import glob
import os
import random

import aiohttp
import click
import oss
import yaml
from loguru import logger
from sc2.client import Client
from sc2.data import AIBuild, Difficulty, Race
from sc2.main import _host_game, _play_game
from sc2.maps import Map
from sc2.paths import Paths
from sc2.player import Bot, Computer
from sc2.portconfig import Portconfig
from sc2.protocol import ConnectionAlreadyClosed

from phantom.common.utils import async_command
from phantom.config import BotConfig
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
@click.option("--maps-path", default=str(Paths.MAPS))
@click.option("--map-pattern", default="*")
@click.option("--enemy-race", default=Race.Random.name, type=click.Choice([x.name for x in Race]))
@click.option(
    "--enemy-difficulty",
    default=Difficulty.CheatInsane.name,
    type=click.Choice([x.name for x in Difficulty]),
)
@click.option("--enemy-build", default=AIBuild.Rush.name, type=click.Choice([x.name for x in AIBuild]))
@async_command
async def run(
    config: str,
    bot_config: str,
    game_port: int,
    start_port: int,
    ladder_server: str,
    opponent_id: str,
    realtime: bool,
    save_replay: str,
    maps_path: str,
    map_pattern: str,
    enemy_race: str,
    enemy_difficulty: str,
    enemy_build: str,
):
    logger.info("Setting up bot...")
    logger.info(maps_path)
    if bot_config is not None:
        bot_config_value = BotConfig.from_yaml(bot_config)
    else:
        bot_config_value = BotConfig()
    bot_config_value.opponent_id = opponent_id
    ai = PhantomBot(bot_config_value)
    race = ai.pick_race()
    bot = Bot(race, ai, ai.name)
    if save_replay:
        replay_path = os.path.join(save_replay, f"{datetime.datetime.now():%Y-%m-%d-%H-%M-%S}.SC2REPLAY")
        logger.info(f"Saving replay to {replay_path=}")
        os.makedirs(save_replay, exist_ok=True)
    else:
        replay_path = None

    if ladder_server:
        logger.info("Starting ladder game...")
        port_config = Portconfig(
            server_ports=[start_port + 2, start_port + 3], player_ports=[[start_port + 4, start_port + 5]]
        )
        ws_url = f"ws://{ladder_server}:{game_port}/sc2api"
        ws_connection = await aiohttp.ClientSession().ws_connect(ws_url)
        client = Client(ws_connection)
        game_time_limit = None

        try:
            result = await _play_game(bot, client, realtime, port_config, game_time_limit)
            if save_replay:
                await client.save_replay(replay_path)
        except ConnectionAlreadyClosed:
            logger.error("Connection was closed before the game ended")
            return None
        finally:
            await ws_connection.close()

    else:
        logger.info("Starting local game...")

        map_choices = glob.glob(os.path.join(maps_path, f"{map_pattern}.SC2MAP"))
        map_choice = random.choice(map_choices)
        logger.info(f"Map pick is {map_choice=}")
        opponent = Computer(Race[enemy_race], Difficulty[enemy_difficulty], AIBuild[enemy_build])

        result = await _host_game(
            Map(map_choice),
            [bot, opponent],
            realtime=realtime,
            save_replay_as=replay_path,
        )

    logger.info(f"Game finished with {result=}")


if __name__ == "__main__":
    run()
