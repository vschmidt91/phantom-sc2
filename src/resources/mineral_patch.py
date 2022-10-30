from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from sc2.position import Point2
from sc2.unit import Unit

from .resource_unit import ResourceUnit
from ..constants import RICH_MINERALS

class MineralPatch(ResourceUnit):

    def __init__(self, unit: Unit) -> None:
        super().__init__(unit)
        self.speedmining_target: Point2 = unit.position

    @property
    def is_rich(self) -> bool:
        if not self.unit:
            return False
        else:
            return self.unit.type_id in RICH_MINERALS

    @property
    def remaining(self) -> int:
        if not self.unit:
            return 0
        elif not self.unit.is_visible:
            return 1500
        else:
            return self.unit.mineral_contents

    @property
    def harvester_target(self) -> int:
        return 2 if self.remaining else 0
