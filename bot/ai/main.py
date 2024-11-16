from sc2.data import Race
from sklearn.linear_model import SGDRegressor
from sklearn.multioutput import MultiOutputRegressor

from bot.ai.observation import Observation
from bot.ai.utils import unit_composition_to_vector, vector_to_unit_composition
from bot.common.unit_composition import UnitComposition


class AI:

    def __init__(self):
        self.regressor = MultiOutputRegressor(SGDRegressor())
        observation = Observation(
            game_loop=0,
            composition=UnitComposition({}),
            enemy_composition=UnitComposition({}),
            race=Race.Random,
            enemy_race=Race.Random,
        )
        self.train_one(observation, UnitComposition({}))

    def predict(self, observation: Observation) -> UnitComposition:
        x = observation.to_array().reshape(1, -1)
        y = self.regressor.predict(x)[0, :]
        inferred_composition = vector_to_unit_composition(y)
        inferred_composition = UnitComposition({k: v for k, v in inferred_composition.items() if v > 0})
        return inferred_composition

    def train_one(self, observation: Observation, target: UnitComposition):
        x = observation.to_array().reshape(1, -1)
        y = unit_composition_to_vector(target).reshape(1, -1)
        self.regressor.partial_fit(x, y)
