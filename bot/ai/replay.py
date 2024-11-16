import glob
import lzma
import pickle
from dataclasses import dataclass
from functools import cached_property
from typing import Iterable

import mpyq
import s2protocol
import s2protocol.versions
from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId

from bot.ai.observation import Observation
from bot.common.unit_composition import UnitComposition

FILES = [
    "replay.attributes.events",
    "replay.details",
    "replay.details.backup",
    "replay.game.events",
    "replay.gamemetadata.json",
    "replay.initData",
    "replay.initData.backup",
    "replay.load.info",
    "replay.message.events",
    "replay.resumable.events",
    "replay.server.battlelobby",
    "replay.smartcam.events",
    "replay.sync.events",
    "replay.sync.history",
    "replay.tracker.events",
]


@dataclass(frozen=True)
class Replay:
    path: str

    @cached_property
    def archive(self):
        return mpyq.MPQArchive(self.path)

    @cached_property
    def files(self):
        return self.archive.files

    @cached_property
    def header(self):
        contents = self.archive.header['user_data_header']['content']
        return s2protocol.versions.latest().decode_replay_header(contents)

    @cached_property
    def protocol(self):
        build = self.header['m_version']['m_baseBuild']
        return s2protocol.versions.build(build)

    @cached_property
    def details(self):
        return list(self.protocol.decode_replay_details(self.archive.read_file("replay.details")))

    @cached_property
    def game_events(self):
        return list(self.protocol.decode_replay_game_events(self.archive.read_file("replay.game.events")))

    @cached_property
    def message_events(self):
        return list(self.protocol.decode_replay_message_events(self.archive.read_file("replay.message.events")))

    @cached_property
    def tracker_events(self):
        return list(self.protocol.decode_replay_tracker_events(self.archive.read_file("replay.tracker.events")))

    @cached_property
    def attributes_events(self):
        return list(self.protocol.decode_replay_attributes_events(self.archive.read_file("replay.attributes.events")))

    @cached_property
    def observations(self) -> dict[int, Observation]:
        tag_to_player = dict[int, int]()
        observations = dict[int, Observation]()
        composition = UnitComposition({})
        enemy_composition = UnitComposition({})
        last_game_loop = 0
        race = Race.Random
        enemy_race = Race.Random
        for evt in self.tracker_events:
            player_id = evt.get("m_controlPlayerId") or evt.get("m_playerId")
            tag = evt.get("m_unitTagIndex")
            event_type = evt.get("_event")
            if event_type in {"NNet.Replay.Tracker.SPlayerSetupEvent"}:
                r = Race(evt["m_type"])
                if player_id == 1:
                    race = r
                elif player_id == 2:
                    enemy_race = r
            game_loop = evt.get("_gameloop")
            if last_game_loop != game_loop:
                observations[last_game_loop] = Observation(
                    last_game_loop, composition, enemy_composition, race, enemy_race
                )
                last_game_loop = game_loop

            type_bytes = evt.get("m_unitTypeName")
            unit_type = UnitTypeId.COW
            if type_bytes:
                unit_type_str = type_bytes.decode("utf-8").upper()
                unit_type = UnitTypeId[unit_type_str]
            if event_type in {"NNet.Replay.Tracker.SUnitBornEvent", "NNet.Replay.Tracker.SUnitInitEvent"}:
                if player_id == 1:
                    composition += {unit_type: 1}
                elif player_id == 2:
                    enemy_composition += {unit_type: 1}
                tag_to_player[tag] = player_id
            elif event_type == "NNet.Replay.Tracker.SUnitTypeChangeEvent":
                pass
            elif event_type == "NNet.Replay.Tracker.SUnitDiedEvent":
                if player_id := tag_to_player.pop(tag):
                    if player_id == 1:
                        composition -= {unit_type: 1}
                    elif player_id == 2:
                        enemy_composition -= {unit_type: 1}

        return observations


def load_replays(pattern: str) -> Iterable[tuple[Observation, UnitComposition]]:
    for s in glob.iglob(pattern, recursive=True):
        with lzma.open(s, "rb") as f:
            game = pickle.load(f)
        game_loops = sorted(set(game.observations) & set(game.replay.observations))
        for t in game_loops:
            o = game.observations[t]
            t = game.replay.observations[t].enemy_composition
            yield o, t
