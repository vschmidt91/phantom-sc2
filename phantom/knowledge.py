from dataclasses import dataclass
from functools import cached_property

from sc2.position import Point2

from phantom.common.utils import Point
from phantom.common.main import BotBase


@dataclass(frozen=True)
class Knowledge:
    bot: BotBase

    @cached_property
    def return_point(self) -> dict[Point, Point2]:
        return {
            r.position.rounded: base.towards(r, 4)
            for base, resources in self.bot.expansion_locations_dict.items()
            for r in resources
        }

    @cached_property
    def return_distances(self) -> dict[Point, float]:
        result = {}
        for base, resources in self.bot.expansion_locations_dict.items():
            for r in resources:
                p = r.position.rounded
                result[p] = self.bot.speedmining_positions[p].distance_to(self.return_point[p])
        return result
