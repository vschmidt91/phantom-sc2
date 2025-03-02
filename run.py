import pathlib
import subprocess
import sys
from functools import reduce

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
sys.path.append("scs")

if __name__ == "__main__":

    BASE_PATH = pathlib.Path(__file__).parent
    CVXPY_CORE_PATH = (BASE_PATH / "cvxpy" / "cvxpy" / "cvxcore" / "python" / "cvxcore.py").as_posix()
    with open(CVXPY_CORE_PATH) as fi:
        src_in = fi.read()
    src_out = src_in.replace("from . import _cvxcore", "import _cvxcore")
    with open(CVXPY_CORE_PATH, "w") as fo:
        fo.write(src_out)

    from phantom import PhantomBot

    ai = PhantomBot()
    bot = Bot(Race.Zerg, ai, "PhantomBot")
    result, opponent_id = run_ladder_game(bot)
    print(result, " against opponent ", opponent_id)
