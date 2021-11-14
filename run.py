from numpy.lib.stride_tricks import DummyArray
import sc2, sys, os
from __init__ import run_ladder_game
from datetime import datetime
from sc2.main import run_game, run_match
from worker_stack_bot import WorkerStackBot

from sc2.data import Race, Difficulty, AIBuild
from sc2.player import Bot, Computer

# Load bot
from suntzu.zerg import ZergAI
from suntzu.common import PerformanceMode
from suntzu.dummy import DummyAI
from suntzu.strategies.pool12_allin import Pool12AllIn

# Start game
if __name__ == "__main__":
    if "--LadderServer" in sys.argv:
        # Ladder game started by LadderManager
        print("Starting ladder game ...")        
        bot = Bot(Race.Zerg, ZergAI(game_step = 2), 'Sun Tzu')
        result, opponentid = run_ladder_game(bot)
        print(result, " against opponent ", opponentid)
    else:
        # Local game
        print("Starting local game ...")

        time = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
        replayPath = os.path.join("replays", time + ".SC2Replay")
        kwargs = {

        }
        # bot = Bot(Race.Zerg, WorkerStackBot())
        bot = Bot(Race.Zerg, ZergAI(game_step = 8, debug = True, performance = PerformanceMode.DEFAULT), 'Sun Tzu')   
        # opponent = Bot(Race.Protoss, DummyAI())
        # opponent = Computer(Race.Protoss, Difficulty.CheatInsane, ai_build=AIBuild.Macro)
        opponent = Bot(Race.Zerg, ZergAI(performance = PerformanceMode.HIGH_PERFORMANCE, strategy = Pool12AllIn()), 'Pool12AllIn')   
        run_game(
            sc2.maps.get('JagannathaAIE'),
            [bot, opponent],
            realtime=False,
            save_replay_as=replayPath,
        )