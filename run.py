from numpy.lib.stride_tricks import DummyArray
import sc2, sys, os
from __init__ import run_ladder_game
from datetime import datetime
from sc2.main import run_game, run_match

from sc2.data import Race, Difficulty, AIBuild, Result
from sc2.player import Bot, Computer
from src.pool12_allin import Pool12AllIn

# Load bot
from src.zerg import ZergAI
from src.enums import PerformanceMode
from src.dummy import DummyAI

VERSION_PATH = './version.txt'

with open(VERSION_PATH, 'r') as file:
    version = file.readline().replace('\n', '')

# Start game
if __name__ == "__main__":

    ai = Pool12AllIn()
    name = '12PoolBot'
    # ai = ZergAI(version=version)
    # ai.tags.append(version)
    # name = 'SunTzu'

    if "--LadderServer" in sys.argv:

        # Ladder game started by LadderManager
        print("Starting ladder game ...")        
        ai.game_step = 4
        ai.tags.append(version)
        bot = Bot(Race.Zerg, ai, name)
        result, opponentid = run_ladder_game(bot)
        print(result, " against opponent ", opponentid)
    else:

        # Local game
        print("Starting local game ...")

        time = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
        replayPath = os.path.join("replays", time + ".SC2Replay")
        kwargs = {

        }
        ai.game_step = 4
        # ai.debug = True
        
        bot = Bot(Race.Zerg, ai, name)  
        opponent = Computer(Race.Protoss, Difficulty.VeryHard, ai_build=AIBuild.Rush)
        
        result = run_game(
            sc2.maps.get('RomanticideAIE'),
            [bot, opponent],
            realtime=False,
            save_replay_as=replayPath,
            random_seed=6,
        )
        print(result)