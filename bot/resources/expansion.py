from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.resources.group import ResourceGroup
from bot.resources.mineral_patch import MineralPatch
from bot.resources.vespene_geyser import VespeneGeyser
from bot.utils import get_intersections, project_point_onto_line

STATIC_DEFENSE_OFFSET = 4.25
MINING_RADIUS = 1.325

MINERAL_RADIUS = 1.125
HARVESTER_RADIUS = 0.375


class Expansion(ResourceGroup):
    def __init__(self, position: Point2, resources: Units):
        self.townhall: Unit | None = None
        self.mineral_patches = ResourceGroup[MineralPatch](MineralPatch(m) for m in resources.mineral_field)
        self.vespene_geysers = ResourceGroup[VespeneGeyser](VespeneGeyser(g) for g in resources.vespene_geyser)
        super().__init__((self.mineral_patches, self.vespene_geysers), position)

    def set_speedmining_positions(self) -> None:
        for patch in self.mineral_patches:
            target = patch.position.towards(self.position, MINING_RADIUS)
            for patch2 in self.mineral_patches:
                if patch.position == patch2.position:
                    continue
                position = project_point_onto_line(target, target - self.position, patch2.position)
                distance1 = patch.position.distance_to(self.position)
                distance2 = patch2.position.distance_to(self.position)
                if distance1 < distance2:
                    continue
                if MINING_RADIUS <= patch2.position.distance_to(position):
                    continue
                intersections = list(get_intersections(patch.position, MINING_RADIUS, patch2.position, MINING_RADIUS))
                if intersections:
                    intersection1, intersection2 = intersections
                    if intersection1.distance_to(self.position) < intersection2.distance_to(self.position):
                        target = intersection1
                    else:
                        target = intersection2
                    break
            patch.speedmining_target = target
