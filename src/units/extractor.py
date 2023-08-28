from __future__ import annotations

from typing import Optional

from sc2.unit import UnitCommand

from .unit import AIUnit
from ..behaviors.extractor_trick import ExtractorTrickBehavior


class Extractor(ExtractorTrickBehavior):
    def __init__(self, unit: AIUnit) -> None:
        super().__init__(unit)

    def get_command(self) -> Optional[UnitCommand]:
        return self.do_extractor_trick()
