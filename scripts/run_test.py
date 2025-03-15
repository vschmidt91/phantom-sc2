import sys

from sc2 import maps
from sc2.main import run_game
from sc2.data import Difficulty, Race, Result
from sc2.player import Bot, Computer

sys.path.append("src")
sys.path.append("lib")              # required to import ares
sys.path.append("ares-sc2")         # required to import sc2_helper
sys.path.append("ares-sc2/src")     # required to import ares

from phantom.debug import PhantomBotDebug

EXPECTED_RESULT = Result.Defeat


if __name__ == "__main__":
    ai = PhantomBotDebug()
    ai.resign_after_iteration = 10
    bot = Bot(Race.Zerg, ai, "PhantomBot")

    result = run_game(
        maps.get("EquilibriumAIE"),
        [
            bot,
            Computer(Race.Terran, Difficulty.VeryEasy),
        ],
        realtime=False,
    )
    assert result == EXPECTED_RESULT
