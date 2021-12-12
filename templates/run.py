
import sc2, sys
from ladder import run_ladder_game
from sc2.data import Race, Difficulty
from sc2.player import Bot, Computer

from ${package} import ${cls}
bot = Bot(Race.${race}, ${cls}(), '${name}')


# Start game
if __name__ == '__main__':
    if "--LadderServer" in sys.argv:
        # Ladder game started by LadderManager
        print("Starting ladder game...")
        result, opponentid = run_ladder_game(bot)
        print(result," against opponent ", opponentid)
    else:
        # Local game
        print("Starting local game...")
        sc2.run_game(sc2.maps.get("Abyssal Reef LE"), [
            bot,
            Computer(Race.Protoss, Difficulty.VeryHard)
        ], realtime=True)