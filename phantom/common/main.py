import re
from abc import ABC, abstractmethod
from functools import cached_property
from typing import Iterable, Dict

from sc2.units import Units

from ares import AresBot
from sc2.position import Point2

from phantom.common.constants import MICRO_MAP_REGEX, MINING_RADIUS
from phantom.common.cost import CostManager
from phantom.common.utils import MacroId, get_intersections, project_point_onto_line


class BotBase(AresBot, ABC):
    def __init__(self, game_step_override: int | None = None) -> None:
        super().__init__(game_step_override=game_step_override)
        self.cost = CostManager(self)

    @abstractmethod
    def planned_by_type(self, item: MacroId) -> Iterable:
        raise NotImplementedError()

    @cached_property
    def is_micro_map(self):
        return re.match(MICRO_MAP_REGEX, self.game_info.map_name)

    @cached_property
    def expansion_resource_positions(self) -> dict[Point2, list[Point2]]:
        return {b: [r.position for r in rs] for b, rs in self.expansion_locations_dict.items()}

    @cached_property
    def speedmining_positions(self) -> dict[Point2, Point2]:
        result = dict[Point2, Point2]()
        for base_position, resources in self.expansion_locations_dict.items():
            for patch in resources.mineral_field:
                target = patch.position.towards(base_position, MINING_RADIUS)
                for patch2 in resources.mineral_field:
                    if patch.position == patch2.position:
                        continue
                    position = project_point_onto_line(target, target - base_position, patch2.position)
                    distance1 = patch.position.distance_to(base_position)
                    distance2 = patch2.position.distance_to(base_position)
                    if distance1 < distance2:
                        continue
                    if MINING_RADIUS <= patch2.position.distance_to(position):
                        continue
                    intersections = list(
                        get_intersections(patch.position, MINING_RADIUS, patch2.position, MINING_RADIUS)
                    )
                    if intersections:
                        intersection1, intersection2 = intersections
                        if intersection1.distance_to(base_position) < intersection2.distance_to(base_position):
                            target = intersection1
                        else:
                            target = intersection2
                        break
                result[patch.position] = target
        return result
