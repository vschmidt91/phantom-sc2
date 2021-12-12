
import sc2, sys, os
from __init__ import run_ladder_game
from sc2.data import Race
from sc2.player import Bot
from ${package} import ${cls}

# Start game
if __name__ == "__main__":

    if "--LadderServer" in sys.argv:
        bot = Bot(Race.${race}, ${cls}(), '${name}')
        result, opponentid = run_ladder_game(bot)