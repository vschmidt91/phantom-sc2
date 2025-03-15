import sys

from sc2.data import Race
from sc2.player import Bot

sys.path.append("src")
sys.path.append("lib")

from phantom import PhantomBot
from phantom.ladder import run_ladder_game

if __name__ == "__main__":

    ai = PhantomBot()
    bot = Bot(Race.Zerg, ai, "PhantomBot")
    result, opponent_id = run_ladder_game(bot)
    print(result, " against opponent ", opponent_id)
