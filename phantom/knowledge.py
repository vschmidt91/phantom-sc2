from dataclasses import dataclass
from functools import cached_property

from phantom.common.utils import Point
from phantom.common.main import BotBase


@dataclass(frozen=True)
class Knowledge:
    bot: BotBase

    @cached_property
    def return_point(self) -> dict[Point, Point]:
        return {
            r.position.rounded: base.towards(r, 4).rounded
            for base, resources in self.bot.expansion_locations_dict.items()
            for r in resources
        }
