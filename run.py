import datetime
import os
import pathlib
import random
import re
import sys

import aiohttp
import click
from loguru import logger
from sc2.client import Client
from sc2.data import AIBuild, Difficulty, Race
from sc2.main import Result, _host_game, _play_game
from sc2.maps import Map
from sc2.paths import Paths
from sc2.player import Bot, Computer
from sc2.portconfig import Portconfig
from sc2.protocol import ConnectionAlreadyClosed

from phantom.common.constants import LOG_LEVEL_OPTIONS
from phantom.common.utils import async_command
from phantom.config import BotConfig
from phantom.main import PhantomBot
from scripts.utils import CommandWithConfigFile


@click.command(cls=CommandWithConfigFile("config"))
@click.option("--config", type=click.File("rb"))
@click.option("--bot-config")
@click.option("--GamePort", "game_port", type=int)
@click.option("--StartPort", "start_port", type=int)
@click.option("--LadderServer", "ladder_server")
@click.option("--OpponentId", "opponent_id")
@click.option("--RealTime", "realtime", default=False)
@click.option("--save-replay")
@click.option("--maps-path")
@click.option("--map-pattern", default="*")
@click.option("--enemy-race", default=Race.Random.name, type=click.Choice([x.name for x in Race]))
@click.option(
    "--enemy-difficulty",
    default=Difficulty.CheatInsane.name,
    type=click.Choice([x.name for x in Difficulty]),
)
@click.option("--enemy-build", default=AIBuild.Rush.name, type=click.Choice([x.name for x in AIBuild]))
@click.option(
    "--assert-result",
    type=click.Choice([x.name for x in Result]),
)
@click.option("--log-level", default="INFO", type=click.Choice(LOG_LEVEL_OPTIONS), envvar="LOGURU_LEVEL")
@click.option("--log-disable-modules", default=["sc2"], multiple=True)
@async_command
async def run(
    config,
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
    assert_result: str,
    log_level: str,
    log_disable_modules: list[str],
):
    logger.info("Setting up log handlers")
    logger.remove()
    for module in log_disable_modules:
        logger.debug(f"Disabling logging for {module=}")
        logger.disable(module)
    logger.add(sys.stdout, level=log_level)  # Set different levels for different outputs

    if bot_config:
        logger.info(f"Loading {bot_config=}")
        bot_config_value = BotConfig.from_toml(bot_config)
    else:
        logger.info("Using default bot config")
        bot_config_value = BotConfig()
    bot_config_value.opponent_id = opponent_id
    ai = PhantomBot(bot_config_value)
    race = ai.pick_race()
    logger.info(f"Picking {race=}")
    bot = Bot(race, ai, ai.name)
    if save_replay:
        replay_path = os.path.join(save_replay, f"{datetime.datetime.now():%Y-%m-%d-%H-%M-%S}.SC2Replay")
        logger.info(f"Saving replay to {replay_path=}")
        os.makedirs(save_replay, exist_ok=True)
    else:
        replay_path = None

    if ladder_server:
        logger.info("Starting ladder game")
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
        logger.info("Starting local game")
        if maps_path is None:
            logger.info("No maps path provided, falling back to installation folder")
            maps_path = str(Paths.MAPS)
        map_regex = re.compile(map_pattern)
        map_choices = list(filter(map_regex.match, os.listdir(maps_path)))
        logger.info(f"Found {map_choices=}")
        map_choice = random.choice(map_choices)
        logger.info(f"Picking {map_choice=}")
        opponent = Computer(Race[enemy_race], Difficulty[enemy_difficulty], AIBuild[enemy_build])

        result = await _host_game(
            Map(pathlib.Path(map_choice)),
            [bot, opponent],
            realtime=realtime,
            save_replay_as=replay_path,
        )

    logger.info(f"Game finished with {result=}")

    if assert_result and result.name != assert_result:
        raise Exception(f"Expected {assert_result}, got {result.name}")


if __name__ == "__main__":
    run()
