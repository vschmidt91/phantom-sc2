from sc2 import maps
from sc2.main import run_game
from sc2.data import Difficulty, Race, Result
from sc2.player import Bot, Computer

from phantom.debug import PhantomBotDebug


if __name__ == "__main__":
    ai = PhantomBotDebug()
    ai.resign_after_iteration = 1000
    bot = Bot(Race.Zerg, ai, "PhantomBot")

    result = run_game(
        maps.get("EquilibriumAIE"),
        [
            bot,
            Computer(Race.Terran, Difficulty.VeryEasy),
        ],
        realtime=False,
    )
    assert result == Result.Defeat
