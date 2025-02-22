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
from phantom.data.constants import PARAM_PRIORS
from phantom.data.state import DataState, DataUpdate
from phantom.debug import Debug
from phantom.macro.state import MacroId
from phantom.observation import Observation


class PhantomBot(BotBase):

    debug: Debug | None = None
    replay_tags = set[str]()
    agent = Agent()
    version_path = "version.txt"
    data_path = "data/params.pkl.gz"
    data_json_path = "data/params.json"
    data = DataState.from_priors(PARAM_PRIORS)
    parameters: dict | None = None

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

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

        try:
            with gzip.GzipFile(self.data_path, "rb") as f:
                self.data = pickle.load(f)
        except Exception as e:
            print(f"Error loading data file: {e}")

        self.parameters = self.data.sample_parameters()
        print(f"{self.parameters=}")

        if self.config[DEBUG]:
            self.debug = Debug(self)
            await self.debug.on_start()

        if os.path.exists(self.version_path):
            with open(self.version_path) as f:
                await self.add_replay_tag(f"version_{self.version}")

    async def on_step(self, iteration: int):
        await super().on_step(iteration)

        # local only: skip first iteration like on the ladder
        if iteration == 0 and self.config[DEBUG]:
            return

        if self.debug:
            await self.debug.on_step_start()
        async for action in self.agent.step(Observation(self)):
            if not await action.execute(self):
                await self.add_replay_tag("action_failed")
                logger.error(f"Action failed: {action}")
        if self.debug:
            await self.debug.on_step_end()

    # async def on_before_start(self):
    #     await super().on_before_start()
    #
    async def on_end(self, game_result: Result):
        await super().on_end(game_result)

        if self.parameters:
            print("Updating parameters...")
            update = DataUpdate(
                parameters=self.parameters,
                result=game_result,
            )
            new_data = self.data + update
            try:
                with gzip.GzipFile(self.data_path, "wb") as f:
                    pickle.dump(new_data, f)
                with open(self.data_json_path, "w") as f:
                    json.dump(new_data.to_dict(), f, indent=4)
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
