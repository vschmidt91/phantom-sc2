import subprocess
import sys
from sc2.data import Race
from sc2.player import Bot

from ladder import run_ladder_game

sys.path.append("ares-sc2/src/ares")
sys.path.append("ares-sc2/src")
sys.path.append("ares-sc2")
sys.path.append("src")
sys.path.append("river")
sys.path.append("cvxpy")
sys.path.append("cvxpy/cvxpy")


if __name__ == "__main__":

    subprocess.check_output("scripts/compile_cvxpy.sh", timeout=60)
    from phantom import PhantomBot

    ai = PhantomBot()
    bot = Bot(Race.Zerg, ai, "PhantomBot")
    result, opponent_id = run_ladder_game(bot)
    print(result, " against opponent ", opponent_id)
