import re

from cython_extensions import cy_center
from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from phantom.common.constants import MICRO_MAP_REGEX, MINING_RADIUS
from phantom.common.cost import CostManager
from phantom.common.utils import Point, center, get_intersections, project_point_onto_line


class Knowledge:
    def __init__(self, bot: BotAI) -> None:
        self.build_time = {UnitTypeId(t): data.cost.time for t, data in bot.game_data.units.items()}
        self.is_micro_map = re.match(MICRO_MAP_REGEX, bot.game_info.map_name)

        self.expansion_resource_positions = dict[Point, list[Point]]()
        self.return_point = dict[Point, Point2]()
        self.spore_position = dict[Point, Point2]()
        self.speedmining_positions = dict[Point, Point2]()
        self.return_distances = dict[Point, float]()
        self.enemy_start_locations = [tuple(p.rounded) for p in bot.enemy_start_locations]
        self.bases = [] if self.is_micro_map else [p.rounded for p in bot.expansion_locations_list]

        if self.is_micro_map:
            pass
        else:
            worker_radius = bot.workers[0].radius
            for base_position, resources in bot.expansion_locations_dict.items():
                self.spore_position[base_position.rounded] = base_position.towards(
                    Point2(cy_center(resources)), 5.0
                ).rounded
                for geyser in resources.vespene_geyser:
                    target = geyser.position.towards(base_position, geyser.radius + worker_radius)
                    self.speedmining_positions[geyser.position.rounded] = target
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
                        if patch2.position.distance_to(position) >= MINING_RADIUS:
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
                    self.speedmining_positions[patch.position.rounded] = target

                b = tuple(base_position.rounded)
                self.expansion_resource_positions[b] = [tuple(r.position.rounded) for r in resources]
                for r in resources:
                    p = tuple(r.position.rounded)
                    return_point = base_position.towards(r, 3.125)
                    self.return_point[p] = return_point
                    self.return_distances[p] = self.speedmining_positions[p].distance_to(return_point)

        self.cost = CostManager(bot)
        self.race = bot.race
        self.enemy_race = bot.enemy_race
        self.map_size = bot.game_info.map_size
        self.in_mineral_line = {b: tuple(center(self.expansion_resource_positions[b]).rounded) for b in self.bases}
