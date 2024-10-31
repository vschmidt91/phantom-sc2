from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from .mineral_patch import MineralPatch
from .group import ResourceGroup
from .vespene_geyser import VespeneGeyser

STATIC_DEFENSE_OFFSET = 4.25


class Expansion(ResourceGroup):
    def __init__(self, position: Point2, resources: Units):

        self.townhall: Unit | None = None
        self.static_defense: Unit | None = None

        self.mineral_patches = ResourceGroup(MineralPatch(m) for m in resources.mineral_field)
        self.vespene_geysers = ResourceGroup(VespeneGeyser(g) for g in resources.vespene_geyser)
        super().__init__((self.mineral_patches, self.vespene_geysers), position)

        static_defense_position = Point2(self.position.towards(self.mineral_patches.position, STATIC_DEFENSE_OFFSET))
        static_defense_position = static_defense_position.rounded.offset(Point2((0.5, 0.5)))
        self.static_defense_position = static_defense_position
