import glob
import lzma
import os
import pickle

import click
from loguru import logger
from s2clientprotocol import sc2api_pb2 as sc_pb
from sc2.client import Client
from sc2.protocol import ProtocolError
from sc2.sc2process import SC2Process
from tqdm import tqdm

from phantom.common.utils import async_command
from phantom.replay import Replay, ReplayMetadata, ReplayStep, Report
from scripts.utils import update_battle_net_cache


@click.command
@click.argument("replay-dir", type=click.Path(exists=True, file_okay=False))
# "C:\\ProgramData\\Blizzard Entertainment\\Battle.net"
# "/root/StarCraftII/Battle.net"
@click.option("--battlenet-cache", type=click.Path(exists=True, file_okay=False))
@click.option("--game-step", type=int, default=1)
@click.option("--fullscreen", type=bool, default=False)
@click.option("--realtime", type=bool, default=False)
@click.option("--log-disable-modules", default=["sc2"], multiple=True)
@async_command
async def main(
    replay_dir: str,
    battlenet_cache: str,
    game_step: int,
    fullscreen: bool,
    realtime: bool,
    log_disable_modules,
) -> None:
    # logger.add(sys.stdout, level="TRACE")  # Set different levels for different outputs

    for module in log_disable_modules:
        logger.debug(f"Disabling logging for {module=}")
        logger.disable(module)

    replay_paths = glob.glob(os.path.join(replay_dir, "*.SC2Replay"), recursive=True)

    for replay_path in replay_paths:
        if battlenet_cache:
            update_battle_net_cache([replay_path], battlenet_cache)

        with open(replay_path, "rb") as f:
            replay_data = f.read()

        metadata = ReplayMetadata.from_bytes(replay_data)
        logger.info(f"{metadata=}")
        replay_observer = Replay.from_bytes(replay_data)

        ifopts = sc_pb.InterfaceOptions(
            raw=True,
            score=True,
            show_cloaked=True,
            raw_affects_selection=True,
            raw_crop_to_playable_area=False,
        )

        replays = dict[int, Replay]()
        for player_id in replay_observer.player_ids:
            async with SC2Process(
                fullscreen=fullscreen, base_build=metadata.base_build, data_hash=metadata.data_version
            ) as server:
                client = Client(server._ws)
                client.game_step = game_step
                result = await server._execute(
                    start_replay=sc_pb.RequestStartReplay(
                        replay_data=replay_data,
                        observed_player_id=player_id,
                        realtime=realtime,
                        options=ifopts,
                    )
                )

                steps = dict[int, ReplayStep]()
                game_loops = range(0, replay_observer.game_loops, client.game_step)
                for game_loop in tqdm(game_loops, desc=f"{replay_path=}, {player_id=}"):
                    state = await client.observation()
                    observation = state.observation.observation
                    assert observation.game_loop == game_loop
                    steps[game_loop] = ReplayStep.from_observation(observation)

                    try:
                        await client.step()
                    except ProtocolError as error:
                        logger.error(f"Replay ended unexpectedly with {error=}")
                        break

                replays[player_id] = Replay(
                    steps, replay_observer.game_loops, replay_observer.map, replay_observer.player_ids
                )

        report = Report("opponent_id", result, replay_observer, replays)
        report_file = replay_path + ".pkl.xz"
        with lzma.open(report_file, "wb") as f:
            pickle.dump(report, f)


if __name__ == "__main__":
    main()
