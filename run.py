import sc2, sys, os
from __init__ import run_ladder_game
from datetime import datetime
from sc2.main import run_game, run_match
from suntzu.common import PerformanceMode
from suntzu.dummy import DummmyAI
from suntzu.strategies.pool12_allin import Pool12AllIn
from worker_stack_bot import WorkerStackBot

from bots.Chaosbot.Main import Chaosbot

from sc2.data import Race, Difficulty, AIBuild
from sc2.player import Bot, Computer

# Load bot
from suntzu.zerg import ZergAI

# Start game
if __name__ == "__main__":
    if "--LadderServer" in sys.argv:
        # Ladder game started by LadderManager
        print("Starting ladder game...")        
        bot = Bot(Race.Zerg, ZergAI(game_step = 2), 'Sun Tzu')
        result, opponentid = run_ladder_game(bot)
        print(result, " against opponent ", opponentid)
    else:
        # Local game
        print("Starting local game...")

        time = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
        replayPath = os.path.join("replays", time + ".SC2Replay")
        # replayPath = os.path.join("C:\\Users", "Ryzen", "Documents", "StarCraft II", "Accounts", "490189910", "2-S2-1-9348025", "Replays", "Multiplayer", time + ".SC2Replay")
        bot = Bot(Race.Zerg, ZergAI(game_step = 2, debug = True, performance = PerformanceMode.DEFAULT), 'Sun Tzu')   
        # bot = Bot(Race.Zerg, WorkerStackBot())
        # opponent = Bot(Race.Zerg, ZergAI(strategy=Pool12AllIn()), 'Pool12AllIn')
        # opponent = Bot(Race.Terran, Chaosbot())
        opponent = Computer(Race.Protoss, Difficulty.VeryEasy, ai_build=AIBuild.Macro)
        run_game(
            sc2.maps.get('OxideAIE'),
            [bot, opponent],
            realtime=False,
            save_replay_as=replayPath,
        )