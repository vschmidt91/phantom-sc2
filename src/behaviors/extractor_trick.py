from __future__ import annotations

from typing import Optional

from sc2.ids.ability_id import AbilityId
from sc2.unit_command import UnitCommand

from ..units.unit import AIUnit, Behavior


class ExtractorTrickBehavior(Behavior):
    def __init__(self, unit: AIUnit) -> None:
        super().__init__(unit)

    def do_extractor_trick(self) -> Optional[UnitCommand]:
        if self.unit.state.is_ready:
            return None

        if not self.ai.extractor_trick_enabled:
            return None

        if 0 < self.ai.supply_left:
            return None

        self.ai.extractor_trick_enabled = False
        return self.unit.state(AbilityId.CANCEL)
