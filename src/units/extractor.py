from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from sc2.unit import Unit, UnitCommand

from ..behaviors.extractor_trick import ExtractorTrickBehavior

if TYPE_CHECKING:
    from ..ai_base import AIBase


class Extractor(ExtractorTrickBehavior):

    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)

    def get_command(self) -> Optional[UnitCommand]:
        return self.do_extractor_trick()
