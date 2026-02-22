import logging
from pathlib import Path

import click

from phantom.mock.combat_sim import (
    DEFAULT_DATASET_PATH,
    generate_mock_combat_dataset,
    write_mock_combat_dataset,
)


logger = logging.getLogger(__name__)


@click.command()
@click.option("--simulation-count", default=10_000, type=click.IntRange(min=1), show_default=True)
@click.option("--spawn-count", default=10, type=click.IntRange(min=1), show_default=True)
@click.option("--use-position", default=True, show_default=True)
@click.option("--seed", default=1337, type=int, show_default=True)
@click.option("--dataset-path", default=DEFAULT_DATASET_PATH, show_default=True)
def main(simulation_count: int, spawn_count: int, use_position: bool, seed: int, dataset_path: str) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    project_root = Path(__file__).resolve().parent.parent

    logger.info(
        "Generating mock combat dataset simulation_count=%s spawn_count=%s seed=%s path=%s",
        simulation_count,
        spawn_count,
        seed,
        dataset_path,
    )
    results = generate_mock_combat_dataset(
        simulation_count=simulation_count,
        spawn_count=spawn_count,
        use_position=use_position,
        seed=seed,
    )
    write_mock_combat_dataset(results=results, dataset_path=dataset_path, project_root=project_root)


if __name__ == "__main__":
    main()
