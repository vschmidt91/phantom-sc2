import asyncio
import datetime
import os
import pathlib
import random
import re
import sys
from functools import wraps

import aiohttp
import click
from loguru import logger
from sc2.client import Client
from sc2.data import AIBuild, Difficulty, Race
from sc2.main import (
    Result,
    _host_game,
    _join_game,
    _play_game,
    _play_replay,
    _setup_replay,
    get_replay_version,
)
from sc2.maps import Map
from sc2.paths import Paths
from sc2.player import Bot, Computer
from sc2.portconfig import Portconfig
from sc2.protocol import ConnectionAlreadyClosed
from sc2.sc2process import SC2Process

from phantom.common.config import BotConfig
from phantom.dummy import BaseBlock, CannonRush, DummyBot, LoserBot
from phantom.main import PhantomBot
from scripts.utils import CommandWithConfigFile

LOG_LEVEL_OPTIONS = ["TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"]
SPECIAL_BUILDS = {
    "Dummy": DummyBot,
    "BaseBlock": BaseBlock,
    "CannonRush": CannonRush,
    "Loser": LoserBot,
}


def async_command(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


@click.command(cls=CommandWithConfigFile("config"))
@click.option("--config", type=click.File("rb"))
@click.option("--bot-config")
@click.option("--GamePort", "game_port", type=int)
@click.option("--StartPort", "start_port", type=int)
@click.option("--LadderServer", "ladder_server")
@click.option("--OpponentId", "opponent_id")
@click.option("--RealTime", "realtime", default=False)
@click.option("--load-replay", type=click.Path(exists=True, dir_okay=False))
@click.option("--observe-id", default=1, type=int)
@click.option("--save-replay", default="data")
@click.option("--maps-path")
@click.option("--map-pattern", default="*")
@click.option("--enemy-race", default=Race.Random.name, type=click.Choice([x.name for x in Race]))
@click.option(
    "--enemy-difficulty",
    default=Difficulty.CheatInsane.name,
    type=click.Choice([x.name for x in Difficulty]),
)
@click.option(
    "--enemy-build",
    default=AIBuild.Rush.name,
    type=click.Choice([x.name for x in AIBuild] + list(SPECIAL_BUILDS.keys())),
)
@click.option("--game-time-limit", type=float)
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
    load_replay,
    observe_id: int,
    save_replay: str,
    maps_path: str,
    map_pattern: str,
    enemy_race: str,
    enemy_difficulty: str,
    enemy_build: str,
    game_time_limit: float,
    assert_result: str,
    log_level: str,
    log_disable_modules: list[str],
):
    logger.info("Setting up log handlers")
    logger.remove()
    for module in log_disable_modules:
        logger.debug(f"Disabling logging for {module=}")
        logger.disable(module)
    logger.add(sys.stdout, level=log_level.upper())

    if bot_config:
        logger.info(f"Loading {bot_config=}")
        bot_config_value = BotConfig.from_toml(bot_config)
    else:
        logger.info("Using default bot config")
        bot_config_value = BotConfig()
    ai = PhantomBot(bot_config_value, opponent_id)
    race = Race[bot_config_value.race]
    name = bot_config_value.name
    bot = Bot(race, ai, name)
    replay_path = os.path.join(save_replay, f"{datetime.datetime.now():%Y-%m-%d-%H-%M-%S}")
    logger.info(f"Saving replay to {replay_path=}")
    replay_path_sc2 = replay_path + ".SC2Replay"
    os.makedirs(save_replay, exist_ok=True)

    result = Result.Undecided
    if load_replay:
        logger.info(f"Loading replay {load_replay}")
        base_build, data_version = get_replay_version(load_replay)
        async with SC2Process(fullscreen=False, base_build=base_build, data_hash=data_version) as server:
            client = await _setup_replay(server, os.path.abspath(load_replay), realtime, observe_id)
            result = await _play_replay(client, ai, realtime, observe_id)

    elif ladder_server:
        logger.info("Starting ladder game")
        ws_url = f"ws://{ladder_server}:{game_port}/sc2api"
        session = aiohttp.ClientSession()
        port_config = Portconfig(
            server_ports=[start_port + 2, start_port + 3], player_ports=[[start_port + 4, start_port + 5]]
        )
        async with session.ws_connect(ws_url) as ws_connection:
            client = Client(ws_connection, replay_path_sc2)

            try:
                result = await _play_game(bot, client, realtime, port_config, game_time_limit)
            except ConnectionAlreadyClosed:
                logger.error("Connection was closed before the game ended")
            finally:
                await client.quit()

    else:
        logger.info("Starting local game")
        if maps_path is None:
            logger.info("No maps path provided, falling back to installation folder")
            maps_path = str(Paths.MAPS)
        map_regex = re.compile(map_pattern + "\\.SC2(MAP|Map)")
        map_choices = list(filter(map_regex.match, os.listdir(maps_path)))
        logger.info(f"Found {map_choices=}")
        map_choice = random.choice(map_choices)
        logger.info(f"Picking {map_choice=}")

        if special_build := SPECIAL_BUILDS.get(enemy_build):
            logger.info(f"Using special {enemy_build=}")
            opponent = Bot(Race[enemy_race], special_build(), enemy_build, False)
        else:
            opponent = Computer(Race[enemy_race], Difficulty[enemy_difficulty], AIBuild[enemy_build])

        map_settings = Map(pathlib.Path(map_choice))
        players = [bot, opponent]
        kwargs = dict(
            realtime=False,
        )
        if special_build:
            kwargs["portconfig"] = Portconfig()
            result, _ = await asyncio.gather(
                _host_game(map_settings, players, save_replay_as=replay_path_sc2, **kwargs),
                _join_game(players, **kwargs),
                return_exceptions=True,
            )
        else:
            result = await _host_game(map_settings, players, save_replay_as=replay_path_sc2, **kwargs)

    logger.info(f"Game finished with {result=}")

    if isinstance(result, BaseException):
        raise result
    elif isinstance(result, Result) and assert_result and result.name != assert_result:
        raise AssertionError(f"Expected {assert_result}, got {result.name}")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    run()
