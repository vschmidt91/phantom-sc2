from __future__ import annotations

from typing import TYPE_CHECKING, Optional
from sc2.position import Point2


from ..constants import RICH_GAS
from ..units.unit import AIUnit
from .resource_unit import ResourceUnit

if TYPE_CHECKING:
    from src.ai_base import AIBase
    from ..units.structure import Structure


class VespeneGeyser(ResourceUnit):
    def __init__(self, ai: AIBase, position: Point2) -> None:
        super().__init__(ai, position)

    # @functools.cached_property
    @property
    def structure(self) -> Optional[AIUnit]:
        return self.ai.resource_manager.gas_buildings_by_position.get(self.position)

    def on_step(self) -> None:
        return super().on_step()

    @property
    def is_rich(self) -> bool:
        if not self.unit:
            return False
        else:
            return self.unit.type_id in RICH_GAS

    @property
    def remaining(self) -> int:
        if not self.unit:
            return 0
        elif not self.unit.is_visible:
            return 2250
        else:
            return self.unit.vespene_contents

    @property
    def harvester_target(self) -> int:
        if not self.structure:
            return 0
        elif not self.structure.state.is_ready:
            return 0
        elif self.remaining <= 0:
            return 0
        else:
            return 2
