import lzma
import os
import pickle
import random
import sys
from pathlib import Path
from typing import Iterable
import datetime

from sc2 import maps
from sc2.data import AIBuild, Difficulty, Race
from sc2.main import run_game
from sc2.player import AbstractPlayer, Bot, Computer

from ladder import run_ladder_game

sys.path.append("ares-sc2/src/ares")
sys.path.append("ares-sc2/src")
sys.path.append("ares-sc2")

from bot.main import PhantomBot


if __name__ == "__main__":
    bot = Bot(Race.Zerg, PhantomBot(), 'PhantomBot')
    result, opponent_id = run_ladder_game(bot)
    print(result, " against opponent ", opponent_id)
