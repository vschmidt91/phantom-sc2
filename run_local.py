import sys, os
from datetime import datetime

import sc2
from sc2 import Race, Difficulty, AIBuild
from sc2.player import Bot, Computer, Player, Human

from common import CommonAI
from zerg import ZergAI

def main():
    time = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    # replayPath = os.path.join("replays", time + ".SC2Replay")
    replayPath = os.path.join("C:\\Users", "Ryzen", "Documents", "StarCraft II", "Accounts", "490189910", "2-S2-1-9348025", "Replays", "Multiplayer", time + ".SC2Replay")
    sc2.run_game(
        sc2.maps.get("LightshadeLE"),
        [
            Bot(Race.Zerg, ZergAI()),
            Computer(Race.Protoss, Difficulty.VeryHard, ai_build=AIBuild.Macro),
        ],
        realtime=False,
        save_replay_as=replayPath,
    )

if __name__ == "__main__":
    main()