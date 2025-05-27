import contextlib
from collections.abc import Mapping, Set
from dataclasses import dataclass

from mpyq import MPQArchive
from s2protocol import versions
from sc2.bot_ai import BotAI
from sc2.data import Result

from phantom.common.constants import REPLAY_TYPE_ENCODING
from phantom.common.utils import count_sorted


@dataclass(frozen=True, slots=True, order=True)
class ReplayUnit:
    player: int
    type: str


@dataclass(frozen=True, slots=True)
class ReplayUpgrade:
    player: int
    type: str


@dataclass(frozen=True, slots=True)
class ReplayStep:
    units: Mapping[int, ReplayUnit]
    upgrades: Set[ReplayUpgrade]

    def player_compositions(self) -> Mapping[int, Mapping[str, int]]:
        return {player: count_sorted(u.type for u in self.units.values() if u.player == player) for player in [0, 1, 2]}

    def player_upgrades(self) -> Mapping[int, Set[str]]:
        return {player: {u.type for u in self.upgrades if u.player == player} for player in [0, 1, 2]}


@dataclass(frozen=True, slots=True)
class Replay:
    steps: Mapping[int, ReplayStep]

    @classmethod
    def from_file(cls, replay_path: str) -> "Replay":
        archive = MPQArchive(replay_path)
        header = versions.latest().decode_replay_header(archive.header["user_data_header"]["content"])
        protocol = versions.build(header["m_version"]["m_baseBuild"])
        tracker_events = list(protocol.decode_replay_tracker_events(archive.read_file("replay.tracker.events")))

        steps = dict[int, ReplayStep]()
        units = dict[int, ReplayUnit]()
        upgrades = set[ReplayUpgrade]()
        game_loop = 0

        for event in tracker_events:
            event_type = event["_event"]
            event_game_loop = event["_gameloop"]

            if event_game_loop != game_loop:
                steps[game_loop] = ReplayStep(units.copy(), upgrades.copy())
                game_loop = event_game_loop

            try:
                unit_tag = protocol.unit_tag(event["m_unitTagIndex"], event["m_unitTagRecycle"])
            except KeyError:
                unit_tag = 0

            unit_type = event.get("m_unitTypeName", b"").decode(REPLAY_TYPE_ENCODING).upper()
            player = event.get("m_upkeepPlayerId", -1)

            if event_type == "NNet.Replay.Tracker.SPlayerSetupEvent":
                pass
            elif (
                event_type == "NNet.Replay.Tracker.SUnitBornEvent" or event_type == "NNet.Replay.Tracker.SUnitInitEvent"
            ):
                if unit_type.startswith("Beacon"):
                    pass
                else:
                    units[unit_tag] = ReplayUnit(player, unit_type)
            elif event_type == "NNet.Replay.Tracker.SUnitDiedEvent":
                with contextlib.suppress(KeyError):
                    del units[unit_tag]
            elif event_type == "NNet.Replay.Tracker.SUpgradeEvent":
                upgrade_type = event["m_upgradeTypeName"].decode(REPLAY_TYPE_ENCODING).upper()
                if upgrade_type.startswith("Spray"):
                    pass
                else:
                    upgrades.add(ReplayUpgrade(event["m_playerId"], upgrade_type))
            elif event_type == "NNet.Replay.Tracker.SPlayerStatsEvent":
                pass
            elif event_type == "NNet.Replay.Tracker.SUnitTypeChangeEvent":
                units[unit_tag] = ReplayUnit(units[unit_tag].player, unit_type)
            elif (
                event_type == "NNet.Replay.Tracker.SUnitDoneEvent"
                or event_type == "NNet.Replay.Tracker.SUnitPositionsEvent"
            ):
                pass
            elif event_type == "NNet.Replay.Tracker.SUnitOwnerChangeEvent":
                units[unit_tag] = ReplayUnit(player, units[unit_tag].type)
            else:
                raise TypeError(event_type)

        return Replay(steps)


class Recorder:
    def __init__(self):
        self.replay_steps = dict[int, ReplayStep]()

    def record_step(self, bot: BotAI) -> None:
        game_loop = bot.state.game_loop
        units = {u.tag: ReplayUnit(u.owner_id, u.type_id.name) for u in bot.all_units}
        upgrades = {ReplayUpgrade(bot.game_info.players[0].id, u.name) for u in bot.state.upgrades}
        self.replay_steps[game_loop] = ReplayStep(units, upgrades)

    @property
    def replay(self) -> Replay:
        return Replay(self.replay_steps)


@dataclass(frozen=True, slots=True)
class Report:
    opponent_id: str
    result: Result
    replay_observer: Replay
    replay_bot: Replay
