import logging
import lzma
import math
import pickle
import random

import click
from sc2 import maps
from sc2.bot_ai import BotAI
from sc2.data import Difficulty, Race
from sc2.ids.unit_typeid import UnitTypeId
from sc2.main import run_game
from sc2.player import Bot, Computer
from sc2.unit import Unit
from sc2.units import Units
from sc2_helper.combat_simulator import CombatSimulator
from tqdm import tqdm


logger = logging.getLogger(__name__)
DATASET_PATH = "resources/datasets/combat.pkl.xz"


def serialize_unit(unit: Unit) -> dict:
    return dict(
        tag=unit.tag,
        is_enemy=unit.is_enemy,
        is_flying=unit.is_flying,
        health=unit.health,
        shield=unit.shield,
        ground_dps=unit.ground_dps,
        air_dps=unit.air_dps,
        ground_range=unit.ground_range,
        air_range=unit.air_range,
        radius=unit.radius,
        real_speed=unit.real_speed,
        position=(float(unit.position.x), float(unit.position.y)),
    )


class CombatSimBot(BotAI):
    def __init__(self, spawn_count: int, simulation_count: int, use_position: bool) -> None:
        super().__init__()
        self.spawn_count = spawn_count
        self.simulation_count = simulation_count
        self.use_position = use_position

    async def on_step(self, iteration):
        if iteration == 1:
            spawn_types = [
                UnitTypeId.ZERGLING,
                UnitTypeId.ROACH,
                UnitTypeId.QUEEN,
                UnitTypeId.MARINE,
                UnitTypeId.MARAUDER,
                UnitTypeId.HELLION,
                UnitTypeId.ZEALOT,
                UnitTypeId.STALKER,
                UnitTypeId.ADEPT,
            ]
            spawn_position = self.game_info.map_center
            players = [1, 2]
            spawn_commands = [[t, self.spawn_count, spawn_position, p] for t in spawn_types for p in players]
            logger.info("Spawning units: types=%s players=%s spawn_count=%s", len(spawn_types), len(players), self.spawn_count)
            await self.client.debug_create_unit(spawn_commands)

        elif iteration == 2:
            sim = CombatSimulator()
            sim.enable_timing_adjustment(self.use_position)
            logger.info("Running combat simulations: simulation_count=%s", self.simulation_count)

            results = []
            for _ in tqdm(range(self.simulation_count), desc="Combat simulations"):
                army_size = random.randint(1, min(self.units.amount, self.enemy_units.amount) - 1)
                army1 = random.sample(self.units, army_size)
                army2 = random.sample(self.enemy_units, army_size)

                winner, health_remaining = sim.predict_engage(Units(army1, self), Units(army2, self))
                all_units = [*army1, *army2]

                health1 = sum(u.health + u.shield for u in army1)
                health2 = sum(u.health + u.shield for u in army2)

                casualties1 = 1.0
                casualties2 = 1.0
                if winner:
                    casualties1 = (health1 - health_remaining) / health1
                else:
                    casualties2 = (health2 - health_remaining) / health2

                advantage_log = 0.0
                bitterness_log = 0.0
                if casualties1 > 0 and casualties2 > 0:
                    casualties1_log = math.log(casualties1)
                    casualties2_log = math.log(casualties2)
                    advantage_log = (casualties2_log - casualties1_log) / 2
                    bitterness_log = (casualties2_log + casualties1_log) / 2


                results.append(
                    dict(
                        units=list(map(serialize_unit, all_units)),
                        advantage_log=advantage_log,
                        bitterness_log=bitterness_log,
                    )
                )

            logger.info("Writing dataset to %s", DATASET_PATH)
            with lzma.open(DATASET_PATH, "wb") as file:
                pickle.dump(results, file, protocol=pickle.HIGHEST_PROTOCOL)

            logger.info("Simulation complete, leaving game")
            await self.client.leave()


@click.command()
@click.option("--map", "map_name", default="PylonAIE_v4", show_default=True)
@click.option("--simulation-count", default=10_000, type=click.IntRange(min=1), show_default=True)
@click.option("--spawn-count", default=10, type=click.IntRange(min=1), show_default=True)
@click.option("--use-position", default=True, show_default=True)
def main(map_name: str, simulation_count: int, spawn_count: int, use_position: bool) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info(
        "Starting combat data generation map=%s simulation_count=%s spawn_count=%s",
        map_name,
        simulation_count,
        spawn_count,
    )
    run_game(
        maps.get(map_name),
        [
            Bot(Race.Zerg, CombatSimBot(spawn_count=spawn_count, simulation_count=simulation_count, use_position=use_position)),
            Computer(Race.Terran, Difficulty.Medium),
        ],
        realtime=False,
        disable_fog=True,
    )


if __name__ == "__main__":
    main()
