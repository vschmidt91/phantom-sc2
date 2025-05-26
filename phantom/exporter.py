import contextlib
from dataclasses import dataclass
from typing import Any

from s2clientprotocol import sc2api_pb2 as sc_pb
from sc2.bot_ai import BotAI
from sc2.client import Client
from sc2.game_data import GameData
from sc2.game_info import GameInfo
from sc2.game_state import GameState


@dataclass
class BotExport:
    game_data: Any
    game_info: Any
    game_state: Any

    async def create_bot(self) -> BotAI:
        game_data = GameData(self.game_data.data)
        game_info = GameInfo(self.game_info.game_info)
        game_state = GameState(self.game_state)

        bot = BotAI()
        bot._initialize_variables()
        client = Client(True)
        bot._prepare_start(
            client=client,
            player_id=1,
            game_info=game_info,
            game_data=game_data,
        )
        with contextlib.suppress(AttributeError):
            await bot._prepare_step(state=game_state, proto_game_info=self.game_info)
        return bot


class BotExporter(BotAI):
    async def export(self) -> BotExport:
        raw_game_data = await self.client._execute(
            data=sc_pb.RequestData(
                ability_id=True,
                unit_type_id=True,
                upgrade_id=True,
                buff_id=True,
                effect_id=True,
            )
        )
        raw_game_info = await self.client._execute(game_info=sc_pb.RequestGameInfo())
        raw_observation = self.state.response_observation

        return BotExport(
            raw_game_data,
            raw_game_info,
            raw_observation,
        )
