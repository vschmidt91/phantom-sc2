import sys
from os import path

sys.path.append(path.join(path.dirname(__file__), ".."))

import sc2
from Main import RoachRush
from sc2 import Difficulty, Race
from sc2.player import Bot, Computer

bot = Bot(Race.Zerg, RoachRush())

# Start game
if __name__ == "__main__":
    sc2.run_game(
        sc2.maps.get("AcolyteLE"),
        [
            bot,
            Computer(Race.Protoss, Difficulty.Hard),
        ],
        realtime=False,
    )
