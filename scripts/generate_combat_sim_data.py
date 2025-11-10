import json
import random

from sc2 import maps
from sc2.bot_ai import BotAI
from sc2.data import Difficulty, Race
from sc2.ids.unit_typeid import UnitTypeId
from sc2.main import run_game
from sc2.player import Bot, Computer
from sc2.unit import Unit
from sc2.units import Units
from sc2_helper.combat_simulator import CombatSimulator


def serialize_unit(unit: Unit) -> dict:
    return dict(
        health=unit.health,
        shield=unit.shield,
        movement_speed=unit.movement_speed,
        ground_range=unit.ground_range,
        ground_dps=unit.ground_dps,
        air_range=unit.air_range,
        air_dps=unit.air_dps,
        is_flying=unit.is_flying,
    )


class CombatSimBot(BotAI):
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
            spawn_count = 8
            spawn_position = self.game_info.map_center
            players = [1, 2]
            spawn_commands = [[t, spawn_count, spawn_position, p] for t in spawn_types for p in players]
            await self.client.debug_create_unit(spawn_commands)

        elif iteration == 2:
            simulation_count = 10000
            sim = CombatSimulator()

            results = []
            for _ in range(simulation_count):
                army_size = random.randint(1, min(self.units.amount, self.enemy_units.amount) - 1)
                army1 = random.sample(self.units, army_size)
                army2 = random.sample(self.enemy_units, army_size)

                winner, health_remaining = sim.predict_engage(Units(army1, self), Units(army2, self))

                results.append(
                    dict(
                        army1=list(map(serialize_unit, army1)),
                        army2=list(map(serialize_unit, army2)),
                        result=health_remaining if winner else -health_remaining,
                    )
                )

            with open("../resources/datasets/combat.json", "w") as file:
                json.dump(results, file, indent=4)

            await self.client.leave()


def main():
    run_game(
        maps.get("PylonAIE_v4"),
        [Bot(Race.Zerg, CombatSimBot()), Computer(Race.Terran, Difficulty.Medium)],
        realtime=False,
        disable_fog=True,
    )


if __name__ == "__main__":
    main()
