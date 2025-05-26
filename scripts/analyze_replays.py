import lzma
import pickle

import click

from phantom.replay import Replay


@click.command
@click.argument("replay-files", type=click.Path(), nargs=-1)
def main(
    replay_files,
) -> None:
    for replay_file in replay_files:
        replay = Replay.from_file(replay_file)
        with lzma.open(replay_file + ".analyzed.pkl.xz", "w") as output:
            pickle.dump(replay, output)


if __name__ == "__main__":
    main()
