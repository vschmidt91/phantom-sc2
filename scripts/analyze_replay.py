import glob
from collections.abc import Iterable

import click
import pandas as pd
import pyarrow
from loguru import logger
from pyarrow.parquet import ParquetWriter
from s2clientprotocol import sc2api_pb2 as sc_pb
from s2clientprotocol.sc2api_pb2 import Observation
from sc2.client import Client
from sc2.protocol import ProtocolError
from sc2.sc2process import SC2Process
from tqdm import tqdm

from phantom.common.utils import async_command
from phantom.replay import ReplayMetadata
from scripts.utils import update_battle_net_cache


class ObservationWriter:
    def __init__(self, path: str) -> None:
        self.schema = pyarrow.schema(
            [
                ("game_loop", pyarrow.int32()),
                ("player", pyarrow.int8()),
                ("owner", pyarrow.int8()),
                ("tag", pyarrow.int64()),
                ("unit_type", pyarrow.int32()),
                ("x", pyarrow.float32()),
                ("y", pyarrow.float32()),
                ("health", pyarrow.float32()),
                ("shield", pyarrow.float32()),
            ]
        )
        self.path = path

    def __enter__(self) -> "ObservationWriter":
        self.writer = ParquetWriter(self.path, self.schema)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.writer.close()

    def write_observation(self, observation: Observation, **kwargs) -> None:
        records = self._get_records(observation, game_loop=observation.game_loop, **kwargs)
        table = pyarrow.table(pd.DataFrame.from_records(records), schema=self.schema)
        self.writer.write_table(table)

    def _get_records(self, observation: Observation, **kwargs) -> Iterable[dict]:
        for unit in observation.raw_data.units:
            if unit.owner in {1, 2}:
                yield {
                    "owner": unit.owner,
                    "tag": unit.tag,
                    "unit_type": unit.unit_type,
                    "x": unit.pos.x,
                    "y": unit.pos.y,
                    "health": unit.health,
                    "shield": unit.shield,
                    **kwargs,
                }


@click.command
@click.argument("replay-glob", type=str)
# "C:\\ProgramData\\Blizzard Entertainment\\Battle.net"
# "/root/StarCraftII/Battle.net"
@click.option("--battlenet-cache", type=click.Path(exists=True, file_okay=False))
@click.option("--game-step", type=int, default=1)
@click.option("--fullscreen", type=bool, default=False)
@click.option("--realtime", type=bool, default=False)
@async_command
async def main(
    replay_glob: str,
    battlenet_cache: str,
    game_step: int,
    fullscreen: bool,
    realtime: bool,
) -> None:
    logger.disable("sc2")

    logger.info(f"{replay_glob=}")
    replay_paths = glob.glob(replay_glob)
    logger.info(f"{replay_paths=}")

    for replay_path in replay_paths:
        dataset_file = replay_path + ".parquet"

        if battlenet_cache:
            update_battle_net_cache([replay_path], battlenet_cache)

        with open(replay_path, "rb") as f:
            replay_data = f.read()

        metadata = ReplayMetadata.from_bytes(replay_data)
        logger.info(f"{metadata=}")

        ifopts = sc_pb.InterfaceOptions(
            raw=True,
            score=True,
            show_cloaked=True,
            raw_affects_selection=True,
            raw_crop_to_playable_area=False,
        )

        with ObservationWriter(dataset_file) as writer:
            for player_id in [1, 2]:
                async with SC2Process(
                    fullscreen=fullscreen, base_build=metadata.base_build, data_hash=metadata.data_version
                ) as server:
                    client = Client(server._ws)
                    client.game_step = game_step
                    await server._execute(
                        start_replay=sc_pb.RequestStartReplay(
                            replay_data=replay_data,
                            observed_player_id=player_id,
                            realtime=realtime,
                            options=ifopts,
                        )
                    )

                    game_loops = range(0, metadata.game_loops, client.game_step)
                    for _ in tqdm(game_loops, desc=f"{replay_path=}, {player_id=}"):
                        state = await client.observation()
                        writer.write_observation(state.context.context, player=player_id)
                        try:
                            await client.step()
                        except ProtocolError as error:
                            logger.error(f"Replay ended unexpectedly with {error=}")
                            break


if __name__ == "__main__":
    main()
