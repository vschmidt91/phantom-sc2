import gzip
import json
import lzma
import os
import pickle
import sys
from sc2.data import Race
from sc2.player import Bot

from ladder import run_ladder_game

sys.path.append("ares-sc2/src/ares")
sys.path.append("ares-sc2/src")
sys.path.append("ares-sc2")
sys.path.append("river")

from bot.main import PhantomBot
from bot.data.constants import PARAM_PRIORS
from bot.data.state import DataUpdate, DataState

DATA_FILE = "data/params.pkl.gz"
DATA_JSON_FILE = "data/params.json"


if __name__ == "__main__":

    data = DataState.from_priors(PARAM_PRIORS)
    try:
        with gzip.GzipFile(DATA_FILE, "rb") as f:
            data = pickle.load(f)
    except Exception as e:
        print(f"Error loading data file: {e}")
    parameters = data.sample_parameters()
    print(f"{parameters=}")

    ai = PhantomBot(parameters=parameters)
    bot = Bot(Race.Zerg, ai, 'PhantomBot')
    result, opponent_id = run_ladder_game(bot)
    print(result, " against opponent ", opponent_id)

    print("Updating parameters...")
    update = DataUpdate(
        parameters=parameters,
        result=result,
    )
    new_data = data + update
    try:
        with gzip.GzipFile(DATA_FILE, "wb") as f:
            pickle.dump(new_data, f)
        with open(DATA_JSON_FILE, "w") as f:
            json.dump(new_data.to_dict(), f, indent=4)
    except Exception as e:
        print(f"Error storing data file: {e}")
