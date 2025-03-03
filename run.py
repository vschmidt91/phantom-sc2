import sys

from sc2.data import Race
from sc2.player import Bot

from ladder import run_ladder_game


sys.path.append("ares-sc2/src/ares")
sys.path.append("ares-sc2/src")
sys.path.append("ares-sc2")
sys.path.append("src")
sys.path.append("bin")
sys.path.append("cvxpy")
sys.path.append("osqp")
sys.path.append("ecos")

from phantom import PhantomBot

if __name__ == "__main__":

    ai = PhantomBot()
    bot = Bot(Race.Zerg, ai, "PhantomBot")
    result, opponent_id = run_ladder_game(bot)
    print(result, " against opponent ", opponent_id)
