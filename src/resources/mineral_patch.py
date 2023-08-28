from __future__ import annotations

from sc2.position import Point2
from sc2.unit import Unit
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.ai_base import AIBase

from ..constants import RICH_MINERALS
from .resource_unit import ResourceUnit


class MineralPatch(ResourceUnit):
    def __init__(self, ai: AIBase, position: Point2) -> None:
        super().__init__(ai, position)
        self.speedmining_target: Point2 = self.position

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
        if self.remaining <= 0:
            return 0
        else:
            return 2
