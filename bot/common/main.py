import re
from abc import ABC, abstractmethod
from functools import cached_property
from typing import Iterable, TypeAlias

from ares import AresBot
from sc2.position import Point2

from bot.common.assignment import Assignment
from bot.common.constants import MICRO_MAP_REGEX, MINING_RADIUS
from bot.common.cost import CostManager
from bot.common.utils import MacroId, get_intersections, project_point_onto_line

BlockedPositions: TypeAlias = Assignment[Point2, float]


class BotBase(AresBot, ABC):

    def __init__(self, parameters: dict[str, float], game_step_override: int | None = None) -> None:
        super().__init__(game_step_override=game_step_override)
        self.parameters = parameters
        self.cost = CostManager(self)

    @abstractmethod
    def planned_by_type(self, item: MacroId) -> Iterable:
        raise NotImplementedError()

    @cached_property
    def is_micro_map(self):
        return re.match(MICRO_MAP_REGEX, self.game_info.map_name)

    @cached_property
    def speedmining_positions(self) -> dict[Point2, Point2]:
        result = dict[Point2, Point2]()
        for pos, resources in self.expansion_locations_dict.items():
            for patch in resources.mineral_field:
                target = patch.position.towards(pos, MINING_RADIUS)
                for patch2 in resources.mineral_field:
                    if patch.position == patch2.position:
                        continue
                    position = project_point_onto_line(target, target - pos, patch2.position)
                    distance1 = patch.position.distance_to(pos)
                    distance2 = patch2.position.distance_to(pos)
                    if distance1 < distance2:
                        continue
                    if MINING_RADIUS <= patch2.position.distance_to(position):
                        continue
                    intersections = list(
                        get_intersections(patch.position, MINING_RADIUS, patch2.position, MINING_RADIUS)
                    )
                    if intersections:
                        intersection1, intersection2 = intersections
                        if intersection1.distance_to(pos) < intersection2.distance_to(pos):
                            target = intersection1
                        else:
                            target = intersection2
                        break
                result[patch.position] = target
        return result
