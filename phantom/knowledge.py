import re

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from phantom.common.constants import MICRO_MAP_REGEX, MINING_RADIUS
from phantom.common.cost import CostManager
from phantom.common.utils import Point, center, get_intersections, project_point_onto_line


class Knowledge:
    def __init__(self, bot: BotAI) -> None:
        self.return_point = {
            r.position.rounded: base.towards(r, 4)
            for base, resources in bot.expansion_locations_dict.items()
            for r in resources
        }
        self.build_time = {UnitTypeId(t): data.cost.time for t, data in bot.game_data.units.items()}
        self.is_micro_map = re.match(MICRO_MAP_REGEX, bot.game_info.map_name)
        self.expansion_resource_positions = {
            b.rounded: [r.position.rounded for r in rs] for b, rs in bot.expansion_locations_dict.items()
        }
        self.enemy_start_locations = [tuple(p.rounded) for p in bot.enemy_start_locations]

        self.bases = [] if self.is_micro_map else [p.rounded for p in bot.expansion_locations_list]

        self.speedmining_positions = dict[Point, Point2]()
        worker_radius = bot.workers[0].radius
        for base_position, resources in bot.expansion_locations_dict.items():
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

        self.return_distances = {}
        for resources in bot.expansion_locations_dict.values():
            for r in resources:
                p = r.position.rounded
                self.return_distances[p] = self.speedmining_positions[p].distance_to(self.return_point[p])

        self.cost = CostManager(bot)
        self.race = bot.race

        self.in_mineral_line = {b: tuple(center(self.expansion_resource_positions[b]).rounded) for b in self.bases}
