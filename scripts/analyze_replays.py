import json

import click

from phantom.replay import Replay


@click.command
@click.argument("replay-files", type=click.Path(), nargs=-1)
def main(
    replay_files,
) -> None:
    for replay_file in replay_files:
        replay = Replay.from_file(replay_file)
        replay_json_file = replay_file + ".json"
        with open(replay_json_file, "w") as output:
            json.dump(replay.to_json(), output, indent=4)


if __name__ == "__main__":
    main()
