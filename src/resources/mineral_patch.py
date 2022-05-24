
from __future__ import annotations
from typing import Set, Union, Iterable, Optional, TYPE_CHECKING

from sc2.position import Point2
from sc2.unit import Unit
from sc2.ids.ability_id import AbilityId
from ..constants import RICH_MINERALS

from .resource_base import ResourceBase
from .resource_unit import ResourceUnit

if TYPE_CHECKING:
    from ..ai_base import AIBase

class MineralPatch(ResourceUnit):

    def __init__(self, ai: AIBase, unit: Unit) -> None:
        super().__init__(ai, unit)
        self.speedmining_target: Optional[Point2] = None

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
            return 1350
        else:
            return self.unit.mineral_contents

    @property
    def harvester_target(self) -> int:
        return 2 if self.remaining else 0