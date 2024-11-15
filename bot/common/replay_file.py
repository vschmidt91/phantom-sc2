from collections import defaultdict
from dataclasses import dataclass
from functools import cached_property, cache

import mpyq
import s2protocol
import s2protocol.versions
from sc2.ids.unit_typeid import UnitTypeId

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
class ReplayFile:
    path: str

    @cached_property
    def archive(self):
        return mpyq.MPQArchive(self.path)

    @cached_property
    def files(self):
        return self.archive.files

    @cached_property
    def protocol(self):
        contents = self.archive.header['user_data_header']['content']
        header = s2protocol.versions.latest().decode_replay_header(contents)
        build = header['m_version']['m_baseBuild']
        return s2protocol.versions.build(build)

    @cached_property
    def game_events(self):
        return list(self.protocol.decode_replay_game_events(self.archive.read_file("replay.game.events")))

    @cached_property
    def message_events(self):
        return list(self.protocol.decode_replay_game_events(self.archive.read_file("replay.message.events")))

    @cached_property
    def tracker_events(self):
        return list(self.protocol.decode_replay_tracker_events(self.archive.read_file("replay.tracker.events")))

    @cached_property
    def attributes_events(self):
        return list(self.protocol.decode_replay_attributes_events(self.archive.read_file("replay.attributes.events")))

    @cached_property
    def compositions(self):
        composition = UnitComposition({})
        for evt in self.tracker_events:
            # if not (player_id := evt.get("m_controlPlayerId")):
            #     continue
            if not (event_type := evt.get("_event")):
                continue
            if not (unit_type_bytes := evt.get("m_unitTypeName")):
                continue
            unit_type_str = unit_type_bytes.decode("utf-8").upper()
            unit_type = UnitTypeId[unit_type_str]
            if event_type == "NNet.Replay.Tracker.SUnitBornEvent":
                composition += {unit_type: 1}
            elif event_type == "NNet.Replay.Tracker.SUnitInitEvent":
                composition += {unit_type: 1}
            elif event_type == "NNet.Replay.Tracker.SUnitTypeChangeEvent":
                pass
            elif event_type == "NNet.Replay.Tracker.SUnitDiedEvent":
                composition -= {unit_type: 1}
        return composition
