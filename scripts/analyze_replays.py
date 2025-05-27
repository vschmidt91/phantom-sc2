import lzma
import pickle

import click

from phantom.replay import Report


@click.command
@click.argument("replay-files", type=click.Path(), nargs=-1)
def main(
    replay_files,
) -> None:
    for replay_file in replay_files:
        with lzma.open(replay_file, "rb") as f:
            report: Report = pickle.load(f)
        print(report)


if __name__ == "__main__":
    main()
