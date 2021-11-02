import sc2, sys, os
from __init__ import run_ladder_game
from sc2.data import Race, Difficulty, AIBuild
from sc2.player import Bot, Computer
from datetime import datetime
from sc2.main import run_game
from suntzu.common import PerformanceMode
from suntzu.dummy import DummmyAI

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
        bot = Bot(Race.Zerg, ZergAI(game_step = 8, debug = True, performance = PerformanceMode.HIGH_PERFORMANCE), 'Sun Tzu')   
        # opponent = Bot(Race.Zerg, DummmyAI(), 'Dummy')
        opponent = Computer(Race.Zerg, Difficulty.CheatInsane, ai_build=AIBuild.Macro)
        run_game(
            sc2.maps.get('2000AtmospheresAIE'),
            [bot, opponent],
            realtime=False,
            save_replay_as=replayPath,
        )