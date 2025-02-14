import os
from typing import Iterable

from ares import DEBUG
from loguru import logger

from bot.common.action import Action
from bot.common.constants import VERSION_FILE
from bot.common.main import BotBase
from bot.debug import Debug
from bot.macro.state import MacroId
from bot.observation import Observation
from bot.state import BotState


class PhantomBot(BotBase):

    debug: Debug | None = None
    replay_tags = set[str]()
    agent = BotState()

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    async def add_replay_tag(self, tag: str) -> None:
        if tag not in self.replay_tags:
            self.replay_tags.add(tag)
            await self.client.chat_send(f"Tag:{tag}", True)

    def planned_by_type(self, item: MacroId) -> Iterable:
        return self.agent.macro.planned_by_type(item)

    async def on_start(self) -> None:
        await super().on_start()

        if self.config[DEBUG]:
            self.debug = Debug(self)
            await self.debug.on_start()

        if os.path.exists(VERSION_FILE):
            with open(VERSION_FILE) as f:
                await self.add_replay_tag(f"version_{f.read()}")

    async def on_step(self, iteration: int):
        if iteration == 0:
            if self.config[DEBUG]:  # local only: skip first iteration like on the ladder
                return
        if self.debug:
            await self.debug.on_step_start()
        await super().on_step(iteration)

        observation = Observation(self)
        actions = list[Action]()
        actions.extend([a async for a in self.agent.step(observation)])

        for action in actions:
            success = await action.execute(self)
            if not success:
                await self.add_replay_tag("action_failed")
                logger.error(f"Action failed: {action}")

        if self.debug:
            await self.debug.on_step_end()

    # async def on_before_start(self):
    #     await super().on_before_start()
    #
    # async def on_end(self, game_result: Result):
    #     await super().on_end(game_result)
    #
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
