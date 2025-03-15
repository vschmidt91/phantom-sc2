import gzip
import json
import os
import pickle
from functools import cached_property
from typing import Iterable

from ares import DEBUG
from loguru import logger
from sc2.data import Result

from phantom.agent import Agent
from phantom.common.main import BotBase
from phantom.data.multivariate_normal import NormalParameters
from phantom.data.normal import NormalParameter
from phantom.data.state import DataState
from phantom.macro.state import MacroId
from phantom.observation import Observation
from phantom.parameters import AgentParameters, AgentPrior


class PhantomBot(BotBase):
    replay_tags = set[str]()
    version_path = "version.txt"
    data_path = "data/params.pkl.gz"
    data_json_path = "data/params.json"
    training = True

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        priors = AgentPrior.to_dict()
        try:
            with gzip.GzipFile(self.data_path, "rb") as f:
                self.data = pickle.load(f)
        except Exception as e:
            logger.error(f"Error loading data file, using default values: {e}")
            prior_distribution = NormalParameters.from_independent(priors.values())
            self.data = DataState(prior_distribution, list(priors.keys()))

        self.parameter_values = self.data.parameters.sample() if self.training else self.data.parameters.mean
        parameter_dict = dict(zip(self.data.parameter_names, self.parameter_values))
        parameter_distributions = {k: NormalParameter(float(v), 0, 0) for k, v in parameter_dict.items()}
        parameters = AgentParameters.from_dict(parameter_distributions | priors)
        self.agent = Agent(parameters)

    async def add_replay_tag(self, tag: str) -> None:
        if tag not in self.replay_tags:
            self.replay_tags.add(tag)
            await self.client.chat_send(f"Tag:{tag}", True)

    def planned_by_type(self, item: MacroId) -> Iterable:
        return self.agent.macro.planned_by_type(item)

    @cached_property
    def version(self) -> str:
        with open(self.version_path) as f:
            return f.read()

    async def on_start(self) -> None:
        await super().on_start()

        if os.path.exists(self.version_path):
            await self.add_replay_tag(f"version_{self.version}")

    async def on_step(self, iteration: int):
        await super().on_step(iteration)

        # local only: skip first iteration like on the ladder
        if iteration == 0 and self.config[DEBUG]:
            return

        async for action in self.agent.step(Observation(self)):
            if not await action.execute(self):
                await self.add_replay_tag("action_failed")
                logger.error(f"Action failed: {action}")

    # async def on_before_start(self):
    #     await super().on_before_start()
    #
    async def on_end(self, game_result: Result):
        await super().on_end(game_result)

        if self.agent and self.training:
            print("Updating parameters...")
            self.data.update(self.parameter_values, game_result)
            try:
                with gzip.GzipFile(self.data_path, "wb") as f:
                    pickle.dump(self.data, f)
                with open(self.data_json_path, "w") as f:
                    json.dump(self.data.to_json(), f, indent=4)
            except Exception as e:
                print(f"Error storing data file: {e}")

    # async def on_building_construction_started(self, unit: Unit):
    #     await super().on_building_construction_started(unit)
    #
    # async def on_building_construction_complete(self, unit: Unit):
    #     await super().on_building_construction_complete(unit)
    #
    # async def on_enemy_unit_entered_vision(self, unit: Unit):
    #     await super().on_enemy_unit_entered_vision(unit)
    #
    # async def on_enemy_unit_left_vision(self, unit_tag: int):
    #     await super().on_enemy_unit_left_vision(unit_tag)
    #
    # async def on_unit_destroyed(self, unit_tag: int):
    #     await super().on_unit_destroyed(unit_tag)
    #
    # async def on_unit_created(self, unit: Unit):
    #     await super().on_unit_created(unit)
    #
    # async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId):
    #     await super().on_unit_type_changed(unit, previous_type)
    #
    # async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float):
    #     await super().on_unit_took_damage(unit, amount_damage_taken)
    #
    # async def on_upgrade_complete(self, upgrade: UpgradeId):
    #     await super().on_upgrade_complete(upgrade)
