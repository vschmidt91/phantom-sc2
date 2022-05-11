
from __future__ import annotations
import struct
from typing import Optional, Set, TYPE_CHECKING

from sc2.position import Point2
from sc2.unit import Unit
from sc2.constants import ALL_GAS
from ..constants import RICH_GAS

from .resource_unit import ResourceUnit
from .resource_base import ResourceBase
if TYPE_CHECKING:
    from ..ai_base import AIBase

class VespeneGeyser(ResourceUnit):

    def __init__(self, ai: AIBase, position: Point2) -> None:
        super().__init__(ai, position)

    @property
    def is_rich(self) -> bool:
        if not self.unit:
            return False
        else:
            return self.unit.type_id in RICH_GAS

    @property
    def structure(self) -> Optional[Unit]:
        if (
            (structure := self.ai.unit_manager.structure_by_position.get(self.position))
            and structure.is_vespene_geyser
        ):
            return structure
        else:
            return None

    @property
    def remaining(self) -> int:
        if not self.unit.is_visible:
            return 2250
        else:
            return self.unit.vespene_contents
        # if not self.structure:
        #     return 0
        # elif not self.structure.is_ready:
        #     return 0
        # else:
        #     return self.structure.vespene_contents

    def update(self) -> None:
        self.harvester_target = 3 if self.structure and self.structure.is_ready and self.remaining else 0