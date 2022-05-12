import itertools
from typing import Dict, List, Tuple, Iterable
import sc2, os
from datetime import datetime
from sc2.main import run_game

from sc2.data import Race, Difficulty, AIBuild, Result
from sc2.player import Bot, Computer
from src.pool12_allin import Pool12AllIn
from src.zerg import ZergAI
from src.dummy import DummyAI

if __name__ == "__main__":
    time = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    results_dir = os.path.join("replays", time)
    os.mkdir(results_dir)
    for league in itertools.count():
        league_dir = os.path.join(results_dir, str(1+league))
        os.mkdir(league_dir)
        for map in MAPS:
            for race in RACES:
                for build in BUILDS:
                    replay_path = os.path.join(league_dir, f'{map}-{race.name}-{build.name}.SC2Replay')
                    bot = Bot(Race.Zerg, Pool12AllIn()) 
                    # bot = Bot(Race.Zerg, ZergAI(debug=True), 'Sun Tzu') 
                    opponent = Computer(race, Difficulty.CheatInsane, ai_build=build) 
                    result = run_game(
                        sc2.maps.get(map),
                        [bot, opponent],
                        realtime=False,
                        save_replay_as=replay_path,
                    )
                    results[(race, build)].append(result)
        results_path = os.path.join(league_dir, 'results.txt')
        with open(results_path, 'w') as f:
            for k, v in results.items():
                f.write(f'{k} {v}\n')