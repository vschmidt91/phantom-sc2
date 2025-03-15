import sys
from os import path

sys.path.append(path.join(path.dirname(__file__), ".."))

import sc2
from sc2 import Race, Difficulty
from sc2.player import Bot, Computer

from Main import RoachRush
bot = Bot(Race.Zerg, RoachRush())

# Start game
if __name__ == "__main__":
    sc2.run_game(
        sc2.maps.get("AcolyteLE"),
        [
            bot,
            Computer(Race.Terran, Difficulty.Hard),
        ],
        realtime=False,
    )
