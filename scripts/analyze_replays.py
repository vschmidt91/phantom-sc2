import contextlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence, Set
from dataclasses import dataclass

import click
from mpyq import MPQArchive
from s2protocol import versions

TYPE_ENCODING = "ascii"

type Json = Mapping[str, "Json"] | Sequence["Json"] | str | int | float | bool | None


def count_sorted[T](items: Iterable[T]) -> dict[T, int]:
    return dict(sorted(Counter(items).items()))


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

    def to_json(self) -> Json:
        return {
            player: dict(
                units=count_sorted(u.type for u in self.units.values() if u.player == player),
                upgrades=[u.type for u in self.upgrades if u.player == player],
            )
            for player in [0, 1, 2]
        }


@dataclass(frozen=True, slots=True)
class Replay:
    steps: Mapping[int, ReplayStep]

    def to_json(self) -> Json:
        return {game_loop: step.to_json() for game_loop, step in self.steps.items()}


def read_replay_file(replay_path: str) -> Replay:
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

        unit_type = event.get("m_unitTypeName", b"").decode(TYPE_ENCODING)
        player = event.get("m_upkeepPlayerId", -1)

        if event_type == "NNet.Replay.Tracker.SPlayerSetupEvent":
            pass
        elif event_type == "NNet.Replay.Tracker.SUnitBornEvent" or event_type == "NNet.Replay.Tracker.SUnitInitEvent":
            if unit_type.startswith("Beacon"):
                pass
            else:
                units[unit_tag] = ReplayUnit(player, unit_type)
        elif event_type == "NNet.Replay.Tracker.SUnitDiedEvent":
            with contextlib.suppress(KeyError):
                del units[unit_tag]
        elif event_type == "NNet.Replay.Tracker.SUpgradeEvent":
            upgrade_type = event["m_upgradeTypeName"].decode(TYPE_ENCODING)
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


@click.command
@click.argument("replay-files", type=click.Path(), nargs=-1)
def main(
    replay_files,
) -> None:
    for replay_file in replay_files:
        replay = read_replay_file(replay_file)
        replay_json_file = replay_file + ".json"
        with open(replay_json_file, "w") as output:
            json.dump(replay.to_json(), output, indent=4)


if __name__ == "__main__":
    main()
