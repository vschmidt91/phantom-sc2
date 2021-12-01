from collections import defaultdict
import itertools
from typing import Dict, List, Tuple, Iterable
import sc2, os
from datetime import datetime
from sc2.main import run_game

from sc2.data import Race, Difficulty, AIBuild, Result
from sc2.player import Bot, Computer
from suntzu.zerg import ZergAI
from suntzu.dummy import DummyAI

maps = [
    'OxideAIE',
    'RomanticideAIE',
    '2000AtmospheresAIE',
    'LightshadeAIE',
    'JagannathaAIE',
    'BlackburnAIE'
]

races = [
    Race.Protoss,
    Race.Terran,
    Race.Zerg,
]

builds = [
    AIBuild.Rush,
    AIBuild.Timing,
    AIBuild.Power,
    AIBuild.Macro,
    AIBuild.Air,
]

results: Dict[Tuple[str, Race, AIBuild], List[Result]] = defaultdict(lambda:list())

def result_to_winrate(result: Result) -> float:
    if result == Result.Victory:
        return 1
    elif result == Result.Defeat:
        return 0
    elif result == Result.Tie:
        return 0.5
    raise Exception

def results_to_winrate(results: Iterable[Result]) -> float:
    return sum(result_to_winrate(r) for r in results) / len(results)

if __name__ == "__main__":
    time = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    results_dir = os.path.join("replays", time)
    os.mkdir(results_dir)
    for league in itertools.count():
        league_dir = os.path.join(results_dir, str(1+league))
        os.mkdir(league_dir)
        for map in maps:
            for race in races:
                for build in builds:
                    replay_path = os.path.join(league_dir, f'{map}-{race.name}-{build.name}.SC2Replay')
                    bot = Bot(Race.Zerg, ZergAI(debug=True), 'Sun Tzu') 
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