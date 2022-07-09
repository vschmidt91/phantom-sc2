from __future__ import annotations

from typing import List, Optional, TYPE_CHECKING

from sc2.unit_command import UnitCommand

from .behavior import Behavior
from ..constants import *
from ..utils import *

if TYPE_CHECKING:
    from ..ai_base import AIBase


class HideBehavior(Behavior):

    def __init__(self, ai: AIBase):
        super().__init__(ai)
        w, h = ai.game_info.map_size
        corner_candidates: List[Point2] = [
            Point2((0, 0)),
            Point2((0, h)),
            Point2((w, 0)),
            Point2((w, h)),
        ]
        self.corner = ai.start_location

    def get_command(self, unit: Unit) -> Optional[UnitCommand]:

        if unit.type_id is not UnitTypeId.MUTALISK:
            return None

        if 7 * 60 < self.ai.time:
            return None

        if unit.distance_to(self.corner) < 3:
            return None

        return unit.move(self.corner)
