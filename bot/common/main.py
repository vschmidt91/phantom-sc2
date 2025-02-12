import re
from abc import ABC, abstractmethod
from functools import cached_property
from typing import Iterable, TypeAlias

from ares import AresBot
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from bot.common.constants import MICRO_MAP_REGEX

MacroId: TypeAlias = UnitTypeId | UpgradeId


class BotBase(AresBot, ABC):

    def __init__(self, parameters: dict[str, float], game_step_override: int | None = None) -> None:
        super().__init__(game_step_override=game_step_override)
        self.parameters = parameters

    @abstractmethod
    def planned_by_type(self, item: MacroId) -> Iterable:
        raise NotImplementedError()

    @cached_property
    def is_micro_map(self):
        return re.match(MICRO_MAP_REGEX, self.game_info.map_name)
